from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping


def _decode_json_mapping(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return None
        if isinstance(decoded, Mapping):
            return dict(decoded)
    return None


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_str(value: Any) -> str | None:
    if value is None:
        return None
    return value if isinstance(value, str) else str(value)


def _coerce_bool(value: Any, *, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def _normalize_submission_kinds(value: Any) -> list[str]:
    supported = (
        "shielded_note_relay_transfer",
        "shielded_command",
    )
    if not isinstance(value, list) or not value:
        return list(supported)
    kinds: list[str] = []
    seen: set[str] = set()
    for item in value:
        if item in supported and item not in seen:
            kinds.append(item)
            seen.add(item)
    return kinds or list(supported)


@dataclass(frozen=True)
class TransactionReceipt:
    success: bool
    tx_hash: str | None
    message: Any
    transaction: dict[str, Any] | None
    execution: dict[str, Any] | None
    raw: dict[str, Any]

    @classmethod
    def from_lookup(cls, raw: Mapping[str, Any]) -> "TransactionReceipt":
        raw_dict = dict(raw)
        result = raw_dict.get("result", {})
        execution = raw_dict.get("execution")
        message = raw_dict.get("message")
        tx_hash = result.get("hash") or raw_dict.get("tx_hash")
        return cls(
            success=bool(raw_dict.get("success")),
            tx_hash=tx_hash,
            message=message,
            transaction=raw_dict.get("transaction"),
            execution=execution if isinstance(execution, dict) else None,
            raw=raw_dict,
        )


@dataclass(frozen=True)
class TransactionSubmission:
    submitted: bool
    accepted: bool | None
    finalized: bool
    tx_hash: str | None
    mode: str
    nonce: int
    stamps_supplied: int
    stamps_estimated: int | None
    message: Any
    response: dict[str, Any]
    receipt: TransactionReceipt | None

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "TransactionSubmission":
        raw_dict = dict(raw)
        receipt = raw_dict.get("receipt")
        return cls(
            submitted=bool(raw_dict.get("submitted")),
            accepted=raw_dict.get("accepted"),
            finalized=bool(raw_dict.get("finalized")),
            tx_hash=raw_dict.get("tx_hash"),
            mode=str(raw_dict.get("mode")),
            nonce=int(raw_dict.get("nonce", 0)),
            stamps_supplied=int(raw_dict.get("stamps_supplied", 0)),
            stamps_estimated=raw_dict.get("stamps_estimated"),
            message=raw_dict.get("message"),
            response=dict(raw_dict.get("response", {})),
            receipt=receipt
            if isinstance(receipt, TransactionReceipt)
            else TransactionReceipt.from_lookup(receipt)
            if isinstance(receipt, Mapping)
            else None,
        )


@dataclass(frozen=True)
class ShieldedRelayerInfoPolicy:
    quote_ttl_seconds: int
    default_expiry_seconds: int
    max_expiry_seconds: int
    min_note_relayer_fee: int
    min_command_relayer_fee: int
    allowed_note_contracts: list[str]
    allowed_command_contracts: list[str]
    allowed_command_targets: list[str]
    raw: dict[str, Any]

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ShieldedRelayerInfoPolicy":
        raw_dict = dict(raw)
        return cls(
            quote_ttl_seconds=_coerce_int(raw_dict.get("quote_ttl_seconds")) or 0,
            default_expiry_seconds=(
                _coerce_int(raw_dict.get("default_expiry_seconds")) or 0
            ),
            max_expiry_seconds=_coerce_int(raw_dict.get("max_expiry_seconds"))
            or 0,
            min_note_relayer_fee=(
                _coerce_int(raw_dict.get("min_note_relayer_fee")) or 0
            ),
            min_command_relayer_fee=(
                _coerce_int(raw_dict.get("min_command_relayer_fee")) or 0
            ),
            allowed_note_contracts=[
                item
                for item in raw_dict.get("allowed_note_contracts", [])
                if isinstance(item, str)
            ],
            allowed_command_contracts=[
                item
                for item in raw_dict.get("allowed_command_contracts", [])
                if isinstance(item, str)
            ],
            allowed_command_targets=[
                item
                for item in raw_dict.get("allowed_command_targets", [])
                if isinstance(item, str)
            ],
            raw=raw_dict,
        )


@dataclass(frozen=True)
class ShieldedRelayerCatalogEntry:
    id: str
    relayer_url: str
    auth_token: str | None
    auth_scheme: str
    public_info: bool
    public_quote: bool
    public_job_lookup: bool
    priority: int
    submission_kinds: list[str]

    @classmethod
    def from_dict(
        cls, raw: Mapping[str, Any], *, index: int = 0
    ) -> "ShieldedRelayerCatalogEntry":
        raw_dict = dict(raw)
        relayer_url = (
            _coerce_str(raw_dict.get("relayer_url"))
            or _coerce_str(raw_dict.get("relayerUrl"))
            or _coerce_str(raw_dict.get("base_url"))
            or _coerce_str(raw_dict.get("baseUrl"))
            or ""
        ).rstrip("/")
        if not relayer_url:
            raise ValueError(
                "shielded relayer entry must define relayer_url/relayerUrl "
                "or base_url/baseUrl"
            )
        auth_token = (
            _coerce_str(raw_dict.get("auth_token"))
            or _coerce_str(raw_dict.get("authToken"))
        )
        priority = _coerce_int(raw_dict.get("priority"))
        return cls(
            id=(_coerce_str(raw_dict.get("id")) or f"relayer-{index + 1}").strip(),
            relayer_url=relayer_url,
            auth_token=(auth_token.strip() or None) if auth_token else None,
            auth_scheme=(
                "bearer"
                if (
                    _coerce_str(raw_dict.get("auth_scheme"))
                    or _coerce_str(raw_dict.get("authScheme"))
                )
                == "bearer"
                else "none"
            ),
            public_info=_coerce_bool(
                raw_dict.get("public_info", raw_dict.get("publicInfo")),
                default=True,
            ),
            public_quote=_coerce_bool(
                raw_dict.get("public_quote", raw_dict.get("publicQuote")),
                default=False,
            ),
            public_job_lookup=_coerce_bool(
                raw_dict.get(
                    "public_job_lookup", raw_dict.get("publicJobLookup")
                ),
                default=False,
            ),
            priority=priority if priority is not None and priority >= 0 else 100,
            submission_kinds=_normalize_submission_kinds(
                raw_dict.get(
                    "submission_kinds", raw_dict.get("submissionKinds")
                )
            ),
        )


@dataclass(frozen=True)
class ShieldedRelayerInfo:
    service: str
    protocol_version: str
    available: bool
    chain_id: str | None
    relayer_account: str | None
    submission_mode: str
    wait_for_tx: bool
    capabilities: dict[str, bool]
    policy: ShieldedRelayerInfoPolicy
    raw: dict[str, Any]

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ShieldedRelayerInfo":
        raw_dict = dict(raw)
        policy_raw = raw_dict.get("policy")
        return cls(
            service=str(raw_dict.get("service", "xian-shielded-relayer")),
            protocol_version=str(raw_dict.get("protocol_version", "v1")),
            available=bool(raw_dict.get("available", False)),
            chain_id=raw_dict.get("chain_id"),
            relayer_account=raw_dict.get("relayer_account"),
            submission_mode=str(raw_dict.get("submission_mode", "checktx")),
            wait_for_tx=bool(raw_dict.get("wait_for_tx", False)),
            capabilities={
                key: bool(value)
                for key, value in raw_dict.get("capabilities", {}).items()
            }
            if isinstance(raw_dict.get("capabilities"), Mapping)
            else {},
            policy=ShieldedRelayerInfoPolicy.from_dict(policy_raw)
            if isinstance(policy_raw, Mapping)
            else ShieldedRelayerInfoPolicy.from_dict({}),
            raw=raw_dict,
        )


@dataclass(frozen=True)
class ShieldedRelayerQuote:
    kind: str
    contract: str
    target_contract: str | None
    chain_id: str | None
    relayer_account: str | None
    relayer_fee: int
    expires_at: str | None
    issued_at: str | None
    policy_version: str | None
    raw: dict[str, Any]

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ShieldedRelayerQuote":
        raw_dict = dict(raw)
        return cls(
            kind=str(raw_dict.get("kind", "")),
            contract=str(raw_dict.get("contract", "")),
            target_contract=raw_dict.get("target_contract"),
            chain_id=raw_dict.get("chain_id"),
            relayer_account=raw_dict.get("relayer_account"),
            relayer_fee=_coerce_int(raw_dict.get("relayer_fee")) or 0,
            expires_at=raw_dict.get("expires_at"),
            issued_at=raw_dict.get("issued_at"),
            policy_version=raw_dict.get("policy_version"),
            raw=raw_dict,
        )


@dataclass(frozen=True)
class ShieldedRelayerInfoResult:
    relayer: ShieldedRelayerCatalogEntry
    info: ShieldedRelayerInfo


@dataclass(frozen=True)
class ShieldedRelayerQuoteResult:
    relayer: ShieldedRelayerCatalogEntry
    quote: ShieldedRelayerQuote


@dataclass(frozen=True)
class ShieldedRelayerJob:
    job_id: str
    kind: str
    status: str
    chain_id: str | None
    relayer_account: str | None
    contract: str | None
    function_name: str | None
    tx_hash: str | None
    submitted_at: str | None
    updated_at: str | None
    error: str | None
    submission: TransactionSubmission | None
    raw: dict[str, Any]

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ShieldedRelayerJob":
        raw_dict = dict(raw)
        submission_raw = raw_dict.get("submission")
        return cls(
            job_id=str(raw_dict.get("job_id", "")),
            kind=str(raw_dict.get("kind", "")),
            status=str(raw_dict.get("status", "unknown")),
            chain_id=raw_dict.get("chain_id"),
            relayer_account=raw_dict.get("relayer_account"),
            contract=raw_dict.get("contract"),
            function_name=raw_dict.get("function_name"),
            tx_hash=raw_dict.get("tx_hash"),
            submitted_at=raw_dict.get("submitted_at"),
            updated_at=raw_dict.get("updated_at"),
            error=raw_dict.get("error"),
            submission=TransactionSubmission.from_dict(submission_raw)
            if isinstance(submission_raw, Mapping)
            else None,
            raw=raw_dict,
        )


@dataclass(frozen=True)
class ShieldedRelayerJobResult:
    relayer: ShieldedRelayerCatalogEntry
    job: ShieldedRelayerJob


@dataclass(frozen=True)
class PerformanceStatus:
    enabled: bool
    tracer_mode: str | None
    node_name: str | None
    chain_id: str | None
    global_metrics: dict[str, Any]
    recent_blocks: list[dict[str, Any]]
    raw: dict[str, Any]

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "PerformanceStatus":
        raw_dict = dict(raw)
        return cls(
            enabled=bool(raw_dict.get("enabled")),
            tracer_mode=raw_dict.get("tracer_mode"),
            node_name=raw_dict.get("node_name"),
            chain_id=raw_dict.get("chain_id"),
            global_metrics=dict(raw_dict.get("global_metrics", {})),
            recent_blocks=list(raw_dict.get("recent_blocks", [])),
            raw=raw_dict,
        )


@dataclass(frozen=True)
class NodeStatus:
    node_id: str | None
    moniker: str | None
    network: str | None
    latest_block_height: int | None
    latest_block_hash: str | None
    latest_app_hash: str | None
    latest_block_time_iso: str | None
    catching_up: bool | None
    raw: dict[str, Any]

    @classmethod
    def from_status_response(cls, raw: Mapping[str, Any]) -> "NodeStatus":
        raw_dict = dict(raw)
        result = raw_dict.get("result", {})
        node_info = result.get("node_info", {})
        sync_info = result.get("sync_info", {})

        latest_height = sync_info.get("latest_block_height")
        try:
            latest_height = (
                int(latest_height) if latest_height is not None else None
            )
        except (TypeError, ValueError):
            latest_height = None

        catching_up = sync_info.get("catching_up")
        if isinstance(catching_up, str):
            catching_up = catching_up.lower() == "true"

        return cls(
            node_id=node_info.get("id"),
            moniker=node_info.get("moniker"),
            network=node_info.get("network"),
            latest_block_height=latest_height,
            latest_block_hash=sync_info.get("latest_block_hash"),
            latest_app_hash=sync_info.get("latest_app_hash"),
            latest_block_time_iso=sync_info.get("latest_block_time"),
            catching_up=(
                bool(catching_up) if isinstance(catching_up, bool) else None
            ),
            raw=raw_dict,
        )


@dataclass(frozen=True)
class BdsStatus:
    worker_running: bool
    catchup_running: bool
    catching_up: bool
    queue_depth: int
    current_block_height: int | None
    height_lag: int | None
    indexed_height: int | None
    spool_pending_count: int
    alerts: list[dict[str, Any]]
    raw: dict[str, Any]

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "BdsStatus":
        raw_dict = dict(raw)
        indexed = raw_dict.get("indexed", {})
        indexed_height = (
            indexed.get("indexed_height")
            if isinstance(indexed, Mapping)
            else None
        )
        return cls(
            worker_running=bool(raw_dict.get("worker_running")),
            catchup_running=bool(raw_dict.get("catchup_running")),
            catching_up=bool(raw_dict.get("catching_up")),
            queue_depth=int(raw_dict.get("queue_depth", 0)),
            current_block_height=raw_dict.get("current_block_height"),
            height_lag=raw_dict.get("height_lag"),
            indexed_height=indexed_height,
            spool_pending_count=int(raw_dict.get("spool_pending_count", 0)),
            alerts=list(raw_dict.get("alerts", [])),
            raw=raw_dict,
        )


@dataclass(frozen=True)
class DeveloperRewardSummary:
    recipient_key: str | None
    total_rewards: str
    reward_count: int
    tx_count: int
    contract_count: int
    first_block_height: int | None
    last_block_height: int | None
    first_reward_at: str | None
    last_reward_at: str | None
    raw: dict[str, Any]

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "DeveloperRewardSummary":
        raw_dict = dict(raw)
        reward_count = raw_dict.get("reward_count", 0)
        tx_count = raw_dict.get("tx_count", 0)
        contract_count = raw_dict.get("contract_count", 0)
        return cls(
            recipient_key=raw_dict.get("recipient_key"),
            total_rewards=str(raw_dict.get("total_rewards", "0")),
            reward_count=int(reward_count),
            tx_count=int(tx_count),
            contract_count=int(contract_count),
            first_block_height=raw_dict.get("first_block_height"),
            last_block_height=raw_dict.get("last_block_height"),
            first_reward_at=raw_dict.get("first_reward_at"),
            last_reward_at=raw_dict.get("last_reward_at"),
            raw=raw_dict,
        )


@dataclass(frozen=True)
class TokenBalance:
    contract: str
    balance: str | None
    name: str | None
    symbol: str | None
    logo_url: str | None
    last_tx_hash: str | None
    last_block_height: int | None
    updated_at: str | None
    raw: dict[str, Any]

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "TokenBalance":
        raw_dict = dict(raw)
        last_block_height = raw_dict.get("last_block_height")
        try:
            last_block_height = (
                int(last_block_height)
                if last_block_height is not None
                else None
            )
        except (TypeError, ValueError):
            last_block_height = None

        balance = raw_dict.get("balance")
        return cls(
            contract=str(raw_dict.get("contract", "")),
            balance=None if balance is None else str(balance),
            name=raw_dict.get("name"),
            symbol=raw_dict.get("symbol"),
            logo_url=raw_dict.get("logo_url"),
            last_tx_hash=raw_dict.get("last_tx_hash"),
            last_block_height=last_block_height,
            updated_at=raw_dict.get("updated_at"),
            raw=raw_dict,
        )


@dataclass(frozen=True)
class TokenBalancePage:
    available: bool
    address: str | None
    items: list[TokenBalance]
    total: int
    limit: int
    offset: int
    raw: dict[str, Any]

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "TokenBalancePage":
        raw_dict = dict(raw)
        raw_items = raw_dict.get("items", [])
        items = [
            TokenBalance.from_dict(item)
            for item in raw_items
            if isinstance(item, Mapping)
        ]
        return cls(
            available=bool(raw_dict.get("available", False)),
            address=raw_dict.get("address"),
            items=items,
            total=int(raw_dict.get("total", len(items))),
            limit=int(raw_dict.get("limit", len(items))),
            offset=int(raw_dict.get("offset", 0)),
            raw=raw_dict,
        )


@dataclass(frozen=True)
class IndexedBlock:
    height: int | None
    block_hash: str | None
    tx_count: int | None
    app_hash: str | None
    block_time_iso: str | None
    raw: dict[str, Any]

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "IndexedBlock":
        raw_dict = dict(raw)
        return cls(
            height=raw_dict.get("height"),
            block_hash=raw_dict.get("block_hash") or raw_dict.get("hash"),
            tx_count=raw_dict.get("tx_count"),
            app_hash=raw_dict.get("app_hash"),
            block_time_iso=raw_dict.get("block_time_iso"),
            raw=raw_dict,
        )


@dataclass(frozen=True)
class IndexedTransaction:
    tx_hash: str | None
    block_height: int | None
    sender: str | None
    nonce: int | None
    contract: str | None
    function: str | None
    success: bool | None
    stamps_used: int | None
    created: str | None
    raw: dict[str, Any]

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "IndexedTransaction":
        raw_dict = dict(raw)
        return cls(
            tx_hash=raw_dict.get("tx_hash"),
            block_height=raw_dict.get("block_height"),
            sender=raw_dict.get("sender"),
            nonce=raw_dict.get("nonce"),
            contract=raw_dict.get("contract"),
            function=raw_dict.get("function"),
            success=raw_dict.get("success"),
            stamps_used=raw_dict.get("stamps_used"),
            created=raw_dict.get("created") or raw_dict.get("created_at"),
            raw=raw_dict,
        )


@dataclass(frozen=True)
class LiveEvent:
    tx_hash: str | None
    block_height: int | None
    tx_index: int | None
    event_index: int | None
    contract: str | None
    event: str | None
    signer: str | None
    caller: str | None
    data_indexed: dict[str, Any] | None
    data: dict[str, Any] | None
    raw: dict[str, Any]

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "LiveEvent":
        raw_dict = dict(raw)
        return cls(
            tx_hash=raw_dict.get("tx_hash"),
            block_height=raw_dict.get("block_height"),
            tx_index=raw_dict.get("tx_index"),
            event_index=raw_dict.get("event_index"),
            contract=raw_dict.get("contract"),
            event=raw_dict.get("event"),
            signer=raw_dict.get("signer"),
            caller=raw_dict.get("caller"),
            data_indexed=_decode_json_mapping(raw_dict.get("data_indexed")),
            data=_decode_json_mapping(raw_dict.get("data")),
            raw=raw_dict,
        )


@dataclass(frozen=True)
class IndexedEvent:
    id: int | None
    tx_hash: str | None
    block_height: int | None
    tx_index: int | None
    event_index: int | None
    contract: str | None
    event: str | None
    signer: str | None
    caller: str | None
    data_indexed: dict[str, Any] | None
    data: dict[str, Any] | None
    created: str | None
    raw: dict[str, Any]

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "IndexedEvent":
        raw_dict = dict(raw)
        return cls(
            id=raw_dict.get("id"),
            tx_hash=raw_dict.get("tx_hash"),
            block_height=raw_dict.get("block_height"),
            tx_index=raw_dict.get("tx_index"),
            event_index=raw_dict.get("event_index"),
            contract=raw_dict.get("contract"),
            event=raw_dict.get("event"),
            signer=raw_dict.get("signer"),
            caller=raw_dict.get("caller"),
            data_indexed=_decode_json_mapping(raw_dict.get("data_indexed")),
            data=_decode_json_mapping(raw_dict.get("data")),
            created=raw_dict.get("created") or raw_dict.get("created_at"),
            raw=raw_dict,
        )


@dataclass(frozen=True)
class ShieldedOutputTag:
    id: int | None
    tx_hash: str | None
    block_height: int | None
    tx_index: int | None
    contract: str | None
    function: str | None
    action: str | None
    output_index: int | None
    note_index: int | None
    commitment: str | None
    new_root: str | None
    payload_hash: str | None
    tag_kind: str | None
    tag_value: str | None
    created: str | None
    raw: dict[str, Any]

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ShieldedOutputTag":
        raw_dict = dict(raw)
        return cls(
            id=raw_dict.get("id"),
            tx_hash=raw_dict.get("tx_hash"),
            block_height=raw_dict.get("block_height"),
            tx_index=raw_dict.get("tx_index"),
            contract=raw_dict.get("contract"),
            function=raw_dict.get("function"),
            action=raw_dict.get("action"),
            output_index=raw_dict.get("output_index"),
            note_index=raw_dict.get("note_index"),
            commitment=raw_dict.get("commitment"),
            new_root=raw_dict.get("new_root"),
            payload_hash=raw_dict.get("payload_hash"),
            tag_kind=raw_dict.get("tag_kind"),
            tag_value=raw_dict.get("tag_value"),
            created=raw_dict.get("created") or raw_dict.get("created_at"),
            raw=raw_dict,
        )


@dataclass(frozen=True)
class ShieldedWalletHistoryEntry:
    event_id: int | None
    tx_hash: str | None
    block_height: int | None
    tx_index: int | None
    contract: str | None
    function: str | None
    action: str | None
    output_index: int | None
    note_index: int | None
    commitment: str | None
    new_root: str | None
    payload_hash: str | None
    output_payload: str | None
    tag_kind: str | None
    tag_value: str | None
    created: str | None
    raw: dict[str, Any]

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ShieldedWalletHistoryEntry":
        raw_dict = dict(raw)
        return cls(
            event_id=raw_dict.get("event_id"),
            tx_hash=raw_dict.get("tx_hash"),
            block_height=raw_dict.get("block_height"),
            tx_index=raw_dict.get("tx_index"),
            contract=raw_dict.get("contract"),
            function=raw_dict.get("function"),
            action=raw_dict.get("action"),
            output_index=raw_dict.get("output_index"),
            note_index=raw_dict.get("note_index"),
            commitment=raw_dict.get("commitment"),
            new_root=raw_dict.get("new_root"),
            payload_hash=raw_dict.get("payload_hash"),
            output_payload=raw_dict.get("output_payload"),
            tag_kind=raw_dict.get("tag_kind"),
            tag_value=raw_dict.get("tag_value"),
            created=raw_dict.get("created") or raw_dict.get("created_at"),
            raw=raw_dict,
        )


@dataclass(frozen=True)
class StateEntry:
    key: str | None
    value: Any
    tx_hash: str | None
    block_height: int | None
    created: str | None
    raw: dict[str, Any]

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "StateEntry":
        raw_dict = dict(raw)
        return cls(
            key=raw_dict.get("key"),
            value=raw_dict.get("value"),
            tx_hash=raw_dict.get("tx_hash"),
            block_height=raw_dict.get("block_height"),
            created=raw_dict.get("created") or raw_dict.get("created_at"),
            raw=raw_dict,
        )
