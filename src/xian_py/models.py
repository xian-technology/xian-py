from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


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
class BdsStatus:
    worker_running: bool
    catchup_running: bool
    queue_depth: int
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
            queue_depth=int(raw_dict.get("queue_depth", 0)),
            height_lag=raw_dict.get("height_lag"),
            indexed_height=indexed_height,
            spool_pending_count=int(raw_dict.get("spool_pending_count", 0)),
            alerts=list(raw_dict.get("alerts", [])),
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
            created=raw_dict.get("created"),
            raw=raw_dict,
        )


@dataclass(frozen=True)
class IndexedEvent:
    tx_hash: str | None
    block_height: int | None
    contract: str | None
    event: str | None
    signer: str | None
    caller: str | None
    created: str | None
    raw: dict[str, Any]

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "IndexedEvent":
        raw_dict = dict(raw)
        return cls(
            tx_hash=raw_dict.get("tx_hash"),
            block_height=raw_dict.get("block_height"),
            contract=raw_dict.get("contract"),
            event=raw_dict.get("event"),
            signer=raw_dict.get("signer"),
            caller=raw_dict.get("caller"),
            created=raw_dict.get("created"),
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
            created=raw_dict.get("created"),
            raw=raw_dict,
        )
