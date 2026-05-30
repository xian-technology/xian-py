from __future__ import annotations

import asyncio
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from xian_py import (
    PAYMENT_IDENTIFIER,
    XianX402Facilitator,
    XianX402PaymentPayload,
    XianX402PaymentRequirement,
    amount_for_contract,
    canonical_amount,
    canonical_permit_amount,
    chain_id_from_xian_network,
    construct_payment_message,
    construct_permit_authorizer_message,
    decode_json_header,
    encode_json_header,
    generate_payment_id,
    is_valid_payment_id,
    sign_xian_x402_payment,
    verify_xian_x402_payment,
    xian_network_id,
)
from xian_py.wallet import Wallet


def _requirement() -> XianX402PaymentRequirement:
    return XianX402PaymentRequirement(
        network=xian_network_id("xian-local-1"),
        asset="currency",
        amount=Decimal("0.0010"),
        pay_to="seller",
        resource="https://api.example.test/data",
    )


def test_payment_id_generation_uses_supported_shape() -> None:
    payment_id = generate_payment_id()

    assert payment_id.startswith("pay_")
    assert is_valid_payment_id(payment_id)
    assert not is_valid_payment_id("short")


def test_canonical_amount_rejects_floats_for_exact_payments() -> None:
    assert canonical_amount("1.2300") == "1.23"
    assert canonical_amount(10) == "10"
    assert amount_for_contract("10") == 10
    assert amount_for_contract("0.001") == Decimal("0.001")
    assert canonical_permit_amount("0.000") == "0"
    assert canonical_permit_amount(100.0) == "100"

    with pytest.raises(TypeError):
        canonical_amount(0.1)


def test_payment_required_header_round_trips() -> None:
    requirement = _requirement()
    encoded = requirement.to_payment_required_header()
    decoded = decode_json_header(encoded)
    restored = XianX402PaymentRequirement.from_payment_required(decoded)

    assert decoded["x402Version"] == 2
    assert decoded["extensions"][PAYMENT_IDENTIFIER]["required"] is True
    assert restored.network == requirement.network
    assert restored.asset == requirement.asset
    assert restored.amount == requirement.amount
    assert restored.pay_to == requirement.pay_to
    assert restored.resource == requirement.resource
    assert restored.extensions[PAYMENT_IDENTIFIER]["required"] is True


def test_payment_payload_signs_and_verifies_both_messages() -> None:
    wallet = Wallet()
    requirement = _requirement()
    payload = sign_xian_x402_payment(
        requirement,
        wallet,
        payment_id="pay_1234567890abcdef",
        deadline="2099-01-01 00:00:00",
        permit_nonce=7,
    )

    result = verify_xian_x402_payment(
        payload,
        requirement,
        now=datetime(2026, 1, 1),
    )

    assert result.valid is True
    assert result.payer == wallet.public_key
    assert result.payment_id == "pay_1234567890abcdef"
    assert payload.permit_nonce == 7


def test_payment_payload_header_round_trips() -> None:
    wallet = Wallet()
    payload = sign_xian_x402_payment(
        _requirement(),
        wallet,
        payment_id="pay_1234567890abcdef",
        deadline="2099-01-01 00:00:00",
    )

    restored = XianX402PaymentPayload.from_header(payload.to_header())

    assert restored == payload
    assert decode_json_header(payload.to_header())["paymentId"] == payload.payment_id


def test_tampered_payment_requirement_fails_verification() -> None:
    wallet = Wallet()
    requirement = _requirement()
    payload = sign_xian_x402_payment(
        requirement,
        wallet,
        payment_id="pay_1234567890abcdef",
        deadline="2099-01-01 00:00:00",
    )
    tampered = XianX402PaymentRequirement(
        network=requirement.network,
        asset=requirement.asset,
        amount=requirement.amount,
        pay_to="attacker",
        resource=requirement.resource,
    )

    result = verify_xian_x402_payment(
        payload,
        tampered,
        now=datetime(2026, 1, 1),
    )

    assert result.valid is False
    assert result.error == "Payment payload does not match requirements."


def test_expired_payment_fails_verification() -> None:
    wallet = Wallet()
    requirement = _requirement()
    payload = sign_xian_x402_payment(
        requirement,
        wallet,
        payment_id="pay_1234567890abcdef",
        deadline="2026-01-01 00:00:00",
    )

    result = verify_xian_x402_payment(
        payload,
        requirement,
        now=datetime(2026, 1, 2),
    )

    assert result.valid is False
    assert result.error == "Payment has expired."


def test_invalid_payment_signature_fails_verification() -> None:
    wallet = Wallet()
    requirement = _requirement()
    payload = sign_xian_x402_payment(
        requirement,
        wallet,
        payment_id="pay_1234567890abcdef",
        deadline="2099-01-01 00:00:00",
    )
    tampered = XianX402PaymentPayload.from_dict(
        {
            **payload.to_dict(),
            "signature": "0" * 128,
        }
    )

    result = verify_xian_x402_payment(
        tampered,
        requirement,
        now=datetime(2026, 1, 1),
    )

    assert result.valid is False
    assert result.error == "Invalid x402 payment signature."


def test_invalid_permit_signature_fails_verification() -> None:
    wallet = Wallet()
    requirement = _requirement()
    payload = sign_xian_x402_payment(
        requirement,
        wallet,
        payment_id="pay_1234567890abcdef",
        deadline="2099-01-01 00:00:00",
    )
    tampered = XianX402PaymentPayload.from_dict(
        {
            **payload.to_dict(),
            "permitSignature": "0" * 128,
        }
    )

    result = verify_xian_x402_payment(
        tampered,
        requirement,
        now=datetime(2026, 1, 1),
    )

    assert result.valid is False
    assert result.error == "Invalid x402 permit signature."


def test_signable_messages_match_contract_profile() -> None:
    message = construct_payment_message(
        x402_version=2,
        scheme="exact",
        network="xian:xian-local-1",
        asset="currency",
        amount="0.001",
        pay_to="seller",
        resource="https://api.example.test/data",
        payer="buyer",
        payment_id="pay_1234567890abcdef",
        deadline="2099-01-01 00:00:00",
        settlement_contract="con_x402_settlement",
    )
    permit_message = construct_permit_authorizer_message(
        token_contract="currency",
        owner="buyer",
        spender="con_x402_settlement",
        value="0.001",
        deadline="2099-01-01 00:00:00",
        authorizer_contract="permit_authorizer",
        chain_id="xian-local-1",
        nonce=12,
    )

    assert message.startswith("xian-x402-exact-v1:")
    assert permit_message == (
        "xian-permit-v2\n"
        "chain_id:xian-local-1\n"
        "authorizer:permit_authorizer\n"
        "token_contract:currency\n"
        "owner:buyer\n"
        "spender:con_x402_settlement\n"
        "amount:0.001\n"
        "deadline:2099-01-01 00:00:00\n"
        "nonce:12"
    )


def test_network_helpers() -> None:
    assert xian_network_id("xian-local-1") == "xian:xian-local-1"
    assert chain_id_from_xian_network("xian:xian-local-1") == "xian-local-1"
    with pytest.raises(ValueError):
        chain_id_from_xian_network("eip155:8453")


def test_json_header_requires_object() -> None:
    encoded = encode_json_header({"ok": True})
    assert decode_json_header(encoded) == {"ok": True}

    with pytest.raises(ValueError):
        decode_json_header("W10=")


def test_payment_required_selection_and_price_guards() -> None:
    requirement = _requirement()
    payload = requirement.to_payment_required()
    payload["accepts"].insert(
        0,
        {
            "scheme": "exact",
            "network": "xian:other-chain",
            "asset": "currency",
            "maxAmountRequired": "2",
            "payTo": "other-seller",
            "resource": "https://api.example.test/other",
        },
    )

    restored = XianX402PaymentRequirement.from_payment_required(
        payload,
        selected_index=1,
    )

    assert restored.network == requirement.network
    assert restored.amount == requirement.amount

    payload["accepts"][1]["maxAmountRequired"] = "$0.01"
    with pytest.raises(ValueError, match="Dollar-denominated"):
        XianX402PaymentRequirement.from_payment_required(
            payload,
            selected_index=1,
        )


class _FakeContract:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def send(self, function: str, **kwargs: object) -> object:
        self.calls.append((function, kwargs))
        return SimpleNamespace(
            submitted=True,
            accepted=True,
            finalized=True,
            receipt=SimpleNamespace(success=True, message=None),
            message=None,
            tx_hash="tx-x402",
        )


class _FakeClient:
    def __init__(self) -> None:
        self.fake_contract = _FakeContract()

    def contract(self, name: str) -> _FakeContract:
        assert name == "con_x402_settlement"
        return self.fake_contract


def test_facilitator_settlement_forwards_chi_defaults() -> None:
    wallet = Wallet()
    requirement = _requirement()
    payload = sign_xian_x402_payment(
        requirement,
        wallet,
        payment_id="pay_1234567890abcdef",
        deadline="2099-01-01 00:00:00",
    )
    client = _FakeClient()
    facilitator = XianX402Facilitator(client=client, requirement=requirement)

    result = asyncio.run(facilitator.settle(payload))

    assert result.success is True
    assert result.transaction == "tx-x402"
    function, kwargs = client.fake_contract.calls[0]
    assert function == "settle"
    assert kwargs["chi_margin"] == 0.0
    assert kwargs["min_chi_headroom"] == 0
    assert kwargs["settlement_contract"] == "con_x402_settlement"
    assert kwargs["permit_nonce"] == payload.permit_nonce


def test_facilitator_rejects_mismatched_payment_before_submission() -> None:
    wallet = Wallet()
    requirement = _requirement()
    payload = sign_xian_x402_payment(
        requirement,
        wallet,
        payment_id="pay_1234567890abcdef",
        deadline="2099-01-01 00:00:00",
    )
    tampered_requirement = XianX402PaymentRequirement(
        network=requirement.network,
        asset=requirement.asset,
        amount="0.002",
        pay_to=requirement.pay_to,
        resource=requirement.resource,
    )
    client = _FakeClient()
    facilitator = XianX402Facilitator(
        client=client,
        requirement=tampered_requirement,
    )

    result = asyncio.run(facilitator.settle(payload))

    assert result.success is False
    assert result.error == "Payment payload does not match requirements."
    assert client.fake_contract.calls == []
