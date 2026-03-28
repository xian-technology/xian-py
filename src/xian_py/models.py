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
            else None,
        )


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
