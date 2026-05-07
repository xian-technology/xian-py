from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import aiohttp

from xian_py.models import TransactionSubmission
from xian_py.wallet import Wallet, verify_msg

PAYMENT_REQUIRED_HEADER = "PAYMENT-REQUIRED"
PAYMENT_SIGNATURE_HEADER = "PAYMENT-SIGNATURE"
PAYMENT_RESPONSE_HEADER = "PAYMENT-RESPONSE"
PAYMENT_IDENTIFIER = "payment-identifier"
DEFAULT_SETTLEMENT_CONTRACT = "con_x402_settlement"
DEFAULT_PERMIT_AUTHORIZER_CONTRACT = "permit_authorizer"
DEFAULT_SETTLEMENT_CHI_MARGIN = 0.25
DEFAULT_SETTLEMENT_MIN_CHI_HEADROOM = 500
XIAN_X402_EXACT_MESSAGE_TAG = "xian-x402-exact-v1"
PAYMENT_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{16,128}$")


def _json_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def encode_json_header(payload: dict[str, Any]) -> str:
    """Encode a JSON object for an x402 HTTP header."""
    return base64.b64encode(_json_dumps(payload).encode("utf-8")).decode(
        "ascii"
    )


def decode_json_header(value: str) -> dict[str, Any]:
    """Decode a base64 JSON x402 HTTP header."""
    payload = json.loads(base64.b64decode(value).decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("x402 header payload must decode to a JSON object.")
    return payload


def generate_payment_id(prefix: str = "pay_") -> str:
    return f"{prefix}{secrets.token_hex(16)}"


def is_valid_payment_id(value: str) -> bool:
    return bool(PAYMENT_ID_PATTERN.fullmatch(value))


def canonical_amount(value: object) -> str:
    if isinstance(value, bool):
        raise TypeError("Amount must not be a boolean.")
    if isinstance(value, float):
        raise TypeError("Use str, int, or Decimal for exact x402 amounts.")
    if isinstance(value, int):
        amount = Decimal(value)
    elif isinstance(value, Decimal):
        amount = value
    elif isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            raise ValueError("Amount must not be empty.")
        try:
            amount = Decimal(normalized)
        except InvalidOperation as exc:
            raise ValueError(f"Invalid amount: {value!r}") from exc
    else:
        raise TypeError(f"Unsupported amount value: {value!r}")

    if amount <= 0:
        raise ValueError("Amount must be positive.")

    text = format(amount.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def amount_for_contract(value: object) -> int | Decimal:
    text = canonical_amount(value)
    if text.isdigit():
        return int(text)
    return Decimal(text)


def contract_deadline(seconds_from_now: int = 300) -> str:
    deadline = datetime.now(timezone.utc) + timedelta(seconds=seconds_from_now)
    return deadline.strftime("%Y-%m-%d %H:%M:%S")


def normalize_contract_time(value: str | datetime) -> str:
    if isinstance(value, str):
        datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        return value
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.strftime("%Y-%m-%d %H:%M:%S")


def parse_contract_time(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")


def xian_network_id(chain_id: str) -> str:
    if not chain_id:
        raise ValueError("chain_id is required.")
    return f"xian:{chain_id}"


def chain_id_from_xian_network(network: str) -> str:
    prefix = "xian:"
    if not network.startswith(prefix) or network == prefix:
        raise ValueError(f"Unsupported Xian x402 network: {network!r}")
    return network[len(prefix) :]


def _sha3_text(value: str) -> str:
    return hashlib.sha3_256(("s:" + value).encode("utf-8")).hexdigest()


def construct_payment_message(
    *,
    x402_version: int,
    scheme: str,
    network: str,
    asset: str,
    amount: str,
    pay_to: str,
    resource: str,
    payer: str,
    payment_id: str,
    deadline: str,
    settlement_contract: str,
) -> str:
    fields = [
        str(x402_version),
        scheme,
        network,
        asset,
        amount,
        pay_to,
        resource,
        payer,
        payment_id,
        deadline,
        settlement_contract,
    ]
    return (
        XIAN_X402_EXACT_MESSAGE_TAG
        + ":"
        + ":".join(_sha3_text(field) for field in fields)
    )


def construct_permit_authorizer_message(
    *,
    token_contract: str,
    owner: str,
    spender: str,
    value: str,
    deadline: str,
    authorizer_contract: str,
    chain_id: str,
) -> str:
    return (
        f"{token_contract}:{owner}:{spender}:{value}:"
        f"{deadline}:{authorizer_contract}:{chain_id}"
    )


@dataclass(frozen=True)
class XianX402PaymentRequirement:
    network: str
    asset: str
    amount: object
    pay_to: str
    resource: str
    settlement_contract: str = DEFAULT_SETTLEMENT_CONTRACT
    scheme: str = "exact"
    x402_version: int = 2
    description: str | None = None
    mime_type: str | None = None
    extensions: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.scheme != "exact":
            raise ValueError("Milestone 1 only supports exact x402 payments.")
        chain_id_from_xian_network(self.network)
        if not self.asset:
            raise ValueError("asset is required.")
        if not self.pay_to:
            raise ValueError("pay_to is required.")
        if not self.resource:
            raise ValueError("resource is required.")
        if not self.settlement_contract:
            raise ValueError("settlement_contract is required.")
        object.__setattr__(self, "amount", canonical_amount(self.amount))

    def to_accepts_item(self) -> dict[str, Any]:
        item: dict[str, Any] = {
            "scheme": self.scheme,
            "network": self.network,
            "asset": self.asset,
            "maxAmountRequired": self.amount,
            "amount": self.amount,
            "payTo": self.pay_to,
            "resource": self.resource,
            "settlementContract": self.settlement_contract,
        }
        if self.description:
            item["description"] = self.description
        if self.mime_type:
            item["mimeType"] = self.mime_type
        return item

    def to_payment_required(self, *, error: str = "") -> dict[str, Any]:
        extensions = dict(self.extensions)
        extensions.setdefault(PAYMENT_IDENTIFIER, {"required": True})
        return {
            "x402Version": self.x402_version,
            "accepts": [self.to_accepts_item()],
            "extensions": extensions,
            "error": error,
        }

    def to_payment_required_header(self, *, error: str = "") -> str:
        return encode_json_header(self.to_payment_required(error=error))

    @classmethod
    def from_payment_required(
        cls,
        payload: dict[str, Any],
        *,
        selected_index: int = 0,
    ) -> "XianX402PaymentRequirement":
        accepts = payload.get("accepts") or payload.get("paymentDetails")
        if not isinstance(accepts, list) or not accepts:
            raise ValueError("Payment required payload has no accepts list.")
        try:
            item = accepts[selected_index]
        except IndexError as exc:
            raise ValueError(
                "Selected payment requirement is missing."
            ) from exc
        if not isinstance(item, dict):
            raise ValueError("Selected payment requirement must be an object.")

        amount = (
            item.get("maxAmountRequired")
            or item.get("amount")
            or item.get("price")
        )
        if isinstance(amount, str) and amount.startswith("$"):
            raise ValueError(
                "Dollar-denominated x402 prices must be resolved to a Xian token amount."
            )
        pay_to = item.get("payTo") or item.get("pay_to")
        settlement_contract = (
            item.get("settlementContract")
            or item.get("settlement_contract")
            or DEFAULT_SETTLEMENT_CONTRACT
        )
        x402_version = payload.get("x402Version") or payload.get(
            "x402_version", 2
        )
        extensions = item.get("extensions") or payload.get("extensions") or {}

        return cls(
            network=str(item.get("network") or ""),
            asset=str(item.get("asset") or ""),
            amount=amount,
            pay_to=str(pay_to or ""),
            resource=str(item.get("resource") or payload.get("resource") or ""),
            settlement_contract=str(settlement_contract),
            scheme=str(item.get("scheme") or "exact"),
            x402_version=int(x402_version),
            description=item.get("description"),
            mime_type=item.get("mimeType") or item.get("mime_type"),
            extensions=extensions if isinstance(extensions, dict) else {},
        )


@dataclass(frozen=True)
class XianX402PaymentPayload:
    network: str
    asset: str
    amount: object
    pay_to: str
    resource: str
    payer: str
    payment_id: str
    deadline: str
    signature: str
    permit_signature: str
    settlement_contract: str = DEFAULT_SETTLEMENT_CONTRACT
    scheme: str = "exact"
    x402_version: int = 2

    def __post_init__(self) -> None:
        chain_id_from_xian_network(self.network)
        if not is_valid_payment_id(self.payment_id):
            raise ValueError("Invalid x402 payment_id.")
        object.__setattr__(self, "amount", canonical_amount(self.amount))
        object.__setattr__(
            self, "deadline", normalize_contract_time(self.deadline)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "x402Version": self.x402_version,
            "scheme": self.scheme,
            "network": self.network,
            "asset": self.asset,
            "amount": self.amount,
            "payTo": self.pay_to,
            "resource": self.resource,
            "payer": self.payer,
            "paymentId": self.payment_id,
            "deadline": self.deadline,
            "settlementContract": self.settlement_contract,
            "signature": self.signature,
            "permitSignature": self.permit_signature,
            "extensions": {
                PAYMENT_IDENTIFIER: {
                    "id": self.payment_id,
                },
            },
        }

    def to_header(self) -> str:
        return encode_json_header(self.to_dict())

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "XianX402PaymentPayload":
        payment_id = payload.get("paymentId") or payload.get("payment_id")
        pay_to = payload.get("payTo") or payload.get("pay_to")
        permit_signature = payload.get("permitSignature") or payload.get(
            "permit_signature"
        )
        settlement_contract = (
            payload.get("settlementContract")
            or payload.get("settlement_contract")
            or DEFAULT_SETTLEMENT_CONTRACT
        )
        x402_version = payload.get("x402Version") or payload.get(
            "x402_version", 2
        )
        return cls(
            network=str(payload.get("network") or ""),
            asset=str(payload.get("asset") or ""),
            amount=payload.get("amount"),
            pay_to=str(pay_to or ""),
            resource=str(payload.get("resource") or ""),
            payer=str(payload.get("payer") or ""),
            payment_id=str(payment_id or ""),
            deadline=str(payload.get("deadline") or ""),
            signature=str(payload.get("signature") or ""),
            permit_signature=str(permit_signature or ""),
            settlement_contract=str(settlement_contract),
            scheme=str(payload.get("scheme") or "exact"),
            x402_version=int(x402_version),
        )

    @classmethod
    def from_header(cls, value: str) -> "XianX402PaymentPayload":
        return cls.from_dict(decode_json_header(value))


@dataclass(frozen=True)
class XianX402VerificationResult:
    valid: bool
    payer: str | None = None
    payment_id: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "payer": self.payer,
            "paymentId": self.payment_id,
            "error": self.error,
        }


@dataclass(frozen=True)
class XianX402SettlementResult:
    success: bool
    network: str
    payment_id: str
    payer: str
    pay_to: str
    asset: str
    amount: str
    transaction: str | None = None
    error: str | None = None
    submission: TransactionSubmission | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "network": self.network,
            "paymentId": self.payment_id,
            "payer": self.payer,
            "payTo": self.pay_to,
            "asset": self.asset,
            "amount": self.amount,
            "transaction": self.transaction,
            "error": self.error,
        }

    def to_header(self) -> str:
        return encode_json_header(self.to_dict())


@dataclass(frozen=True)
class XianX402HTTPResponse:
    status: int
    headers: dict[str, str]
    body: bytes
    payment_required: dict[str, Any] | None = None
    payment_payload: XianX402PaymentPayload | None = None
    payment_response: dict[str, Any] | None = None

    @property
    def text(self) -> str:
        return self.body.decode("utf-8")

    def json(self) -> Any:
        return json.loads(self.text)


def sign_xian_x402_payment(
    requirement: XianX402PaymentRequirement,
    wallet: Wallet,
    *,
    payment_id: str | None = None,
    deadline: str | datetime | None = None,
    permit_authorizer_contract: str = DEFAULT_PERMIT_AUTHORIZER_CONTRACT,
) -> XianX402PaymentPayload:
    payment_id = payment_id or generate_payment_id()
    deadline_text = (
        contract_deadline()
        if deadline is None
        else normalize_contract_time(deadline)
    )
    payer = wallet.public_key
    payment_msg = construct_payment_message(
        x402_version=requirement.x402_version,
        scheme=requirement.scheme,
        network=requirement.network,
        asset=requirement.asset,
        amount=str(requirement.amount),
        pay_to=requirement.pay_to,
        resource=requirement.resource,
        payer=payer,
        payment_id=payment_id,
        deadline=deadline_text,
        settlement_contract=requirement.settlement_contract,
    )
    chain_id = chain_id_from_xian_network(requirement.network)
    permit_msg = construct_permit_authorizer_message(
        token_contract=requirement.asset,
        owner=payer,
        spender=requirement.settlement_contract,
        value=str(requirement.amount),
        deadline=deadline_text,
        authorizer_contract=permit_authorizer_contract,
        chain_id=chain_id,
    )
    return XianX402PaymentPayload(
        network=requirement.network,
        asset=requirement.asset,
        amount=requirement.amount,
        pay_to=requirement.pay_to,
        resource=requirement.resource,
        payer=payer,
        payment_id=payment_id,
        deadline=deadline_text,
        signature=wallet.sign_msg(payment_msg),
        permit_signature=wallet.sign_msg(permit_msg),
        settlement_contract=requirement.settlement_contract,
        scheme=requirement.scheme,
        x402_version=requirement.x402_version,
    )


def verify_xian_x402_payment(
    payload: XianX402PaymentPayload,
    requirement: XianX402PaymentRequirement,
    *,
    permit_authorizer_contract: str = DEFAULT_PERMIT_AUTHORIZER_CONTRACT,
    now: datetime | None = None,
) -> XianX402VerificationResult:
    expected = {
        "x402_version": requirement.x402_version,
        "scheme": requirement.scheme,
        "network": requirement.network,
        "asset": requirement.asset,
        "amount": requirement.amount,
        "pay_to": requirement.pay_to,
        "resource": requirement.resource,
        "settlement_contract": requirement.settlement_contract,
    }
    observed = {
        "x402_version": payload.x402_version,
        "scheme": payload.scheme,
        "network": payload.network,
        "asset": payload.asset,
        "amount": payload.amount,
        "pay_to": payload.pay_to,
        "resource": payload.resource,
        "settlement_contract": payload.settlement_contract,
    }
    if observed != expected:
        return XianX402VerificationResult(
            valid=False,
            payer=payload.payer,
            payment_id=payload.payment_id,
            error="Payment payload does not match requirements.",
        )

    deadline = parse_contract_time(payload.deadline)
    current_time = now or datetime.now(timezone.utc).replace(tzinfo=None)
    if deadline <= current_time:
        return XianX402VerificationResult(
            valid=False,
            payer=payload.payer,
            payment_id=payload.payment_id,
            error="Payment has expired.",
        )

    payment_msg = construct_payment_message(
        x402_version=payload.x402_version,
        scheme=payload.scheme,
        network=payload.network,
        asset=payload.asset,
        amount=str(payload.amount),
        pay_to=payload.pay_to,
        resource=payload.resource,
        payer=payload.payer,
        payment_id=payload.payment_id,
        deadline=payload.deadline,
        settlement_contract=payload.settlement_contract,
    )
    if not verify_msg(payload.payer, payment_msg, payload.signature):
        return XianX402VerificationResult(
            valid=False,
            payer=payload.payer,
            payment_id=payload.payment_id,
            error="Invalid x402 payment signature.",
        )

    permit_msg = construct_permit_authorizer_message(
        token_contract=payload.asset,
        owner=payload.payer,
        spender=payload.settlement_contract,
        value=str(payload.amount),
        deadline=payload.deadline,
        authorizer_contract=permit_authorizer_contract,
        chain_id=chain_id_from_xian_network(payload.network),
    )
    if not verify_msg(payload.payer, permit_msg, payload.permit_signature):
        return XianX402VerificationResult(
            valid=False,
            payer=payload.payer,
            payment_id=payload.payment_id,
            error="Invalid x402 permit signature.",
        )

    return XianX402VerificationResult(
        valid=True,
        payer=payload.payer,
        payment_id=payload.payment_id,
    )


class XianX402Facilitator:
    def __init__(
        self,
        *,
        client: Any,
        requirement: XianX402PaymentRequirement,
        permit_authorizer_contract: str = DEFAULT_PERMIT_AUTHORIZER_CONTRACT,
        settlement_chi_margin: float = DEFAULT_SETTLEMENT_CHI_MARGIN,
        settlement_min_chi_headroom: int = (
            DEFAULT_SETTLEMENT_MIN_CHI_HEADROOM
        ),
    ) -> None:
        self.client = client
        self.requirement = requirement
        self.permit_authorizer_contract = permit_authorizer_contract
        self.settlement_chi_margin = settlement_chi_margin
        self.settlement_min_chi_headroom = settlement_min_chi_headroom

    def verify(
        self, payload: XianX402PaymentPayload
    ) -> XianX402VerificationResult:
        return verify_xian_x402_payment(
            payload,
            self.requirement,
            permit_authorizer_contract=self.permit_authorizer_contract,
        )

    async def settle(
        self,
        payload: XianX402PaymentPayload,
        *,
        mode: str | None = "checktx",
        wait_for_tx: bool | None = True,
        chi: int | None = None,
        chi_margin: float | None = None,
        min_chi_headroom: int | None = None,
    ) -> XianX402SettlementResult:
        verification = self.verify(payload)
        if not verification.valid:
            return XianX402SettlementResult(
                success=False,
                network=payload.network,
                payment_id=payload.payment_id,
                payer=payload.payer,
                pay_to=payload.pay_to,
                asset=payload.asset,
                amount=str(payload.amount),
                error=verification.error,
            )

        submission = await self.client.contract(
            payload.settlement_contract
        ).send(
            "settle",
            token_contract=payload.asset,
            payer=payload.payer,
            pay_to=payload.pay_to,
            amount=amount_for_contract(payload.amount),
            amount_text=str(payload.amount),
            resource=payload.resource,
            payment_id=payload.payment_id,
            deadline=payload.deadline,
            payment_signature=payload.signature,
            permit_signature=payload.permit_signature,
            x402_version=payload.x402_version,
            scheme=payload.scheme,
            network=payload.network,
            permit_authorizer_contract=self.permit_authorizer_contract,
            settlement_contract=payload.settlement_contract,
            mode=mode,
            wait_for_tx=wait_for_tx,
            chi=chi,
            chi_margin=(
                self.settlement_chi_margin if chi_margin is None else chi_margin
            ),
            min_chi_headroom=(
                self.settlement_min_chi_headroom
                if min_chi_headroom is None
                else min_chi_headroom
            ),
        )
        receipt_failed = (
            submission.receipt is not None and not submission.receipt.success
        )
        success = (
            submission.submitted
            and submission.accepted is not False
            and not receipt_failed
            and (not wait_for_tx or submission.finalized)
        )
        error = submission.message
        if receipt_failed and submission.receipt is not None:
            error = submission.receipt.message
        return XianX402SettlementResult(
            success=success,
            network=payload.network,
            payment_id=payload.payment_id,
            payer=payload.payer,
            pay_to=payload.pay_to,
            asset=payload.asset,
            amount=str(payload.amount),
            transaction=submission.tx_hash,
            error=None if success else error,
            submission=submission,
        )


async def x402_request(
    method: str,
    url: str,
    *,
    wallet: Wallet,
    max_amount: object | None = None,
    session: aiohttp.ClientSession | None = None,
    headers: dict[str, str] | None = None,
    **request_kwargs: Any,
) -> XianX402HTTPResponse:
    owned_session = session is None
    if session is None:
        session = aiohttp.ClientSession()

    request_headers = dict(headers or {})
    try:
        async with session.request(
            method,
            url,
            headers=request_headers,
            **request_kwargs,
        ) as response:
            body = await response.read()
            if response.status != 402:
                return XianX402HTTPResponse(
                    status=response.status,
                    headers=dict(response.headers),
                    body=body,
                )

            payment_required = _payment_required_from_response(
                response.headers, body
            )

        requirement = XianX402PaymentRequirement.from_payment_required(
            payment_required
        )
        if max_amount is not None:
            max_amount_text = canonical_amount(max_amount)
            if Decimal(str(requirement.amount)) > Decimal(max_amount_text):
                raise ValueError(
                    f"Payment amount {requirement.amount} exceeds max_amount {max_amount_text}."
                )

        payment_payload = sign_xian_x402_payment(requirement, wallet)
        retry_headers = dict(request_headers)
        retry_headers[PAYMENT_SIGNATURE_HEADER] = payment_payload.to_header()

        async with session.request(
            method,
            url,
            headers=retry_headers,
            **request_kwargs,
        ) as retry_response:
            retry_body = await retry_response.read()
            payment_response = _decode_optional_header(
                retry_response.headers, PAYMENT_RESPONSE_HEADER
            )
            return XianX402HTTPResponse(
                status=retry_response.status,
                headers=dict(retry_response.headers),
                body=retry_body,
                payment_required=payment_required,
                payment_payload=payment_payload,
                payment_response=payment_response,
            )
    finally:
        if owned_session:
            await session.close()


def _payment_required_from_response(
    headers: Any,
    body: bytes,
) -> dict[str, Any]:
    header_value = headers.get(PAYMENT_REQUIRED_HEADER)
    if header_value:
        return decode_json_header(header_value)
    try:
        payload = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("402 response has no payment requirements.") from exc
    if not isinstance(payload, dict):
        raise ValueError("402 response body must be a JSON object.")
    return payload


def _decode_optional_header(headers: Any, name: str) -> dict[str, Any] | None:
    value = headers.get(name)
    if not value:
        return None
    return decode_json_header(value)
