"""
Module-level helpers used by :class:`xian_py.xian_async.XianAsync`.

Factored out of ``xian_async.py`` so the 2000+-line module stays focused
on the public async client surface. These helpers are private to the
``xian_py`` package — external callers should not import them.
"""

from __future__ import annotations

import ast
import json
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import xian_py.transaction as tr
from xian_py.models import LiveEvent
from xian_py.wallet import Wallet


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except TypeError, ValueError:
        return None


def _rpc_ws_url(url: str) -> str:
    parsed = urlsplit(url)
    if not parsed.scheme:
        parsed = urlsplit(f"http://{url}")
    scheme = parsed.scheme.lower()

    if scheme in {"http", "ws"}:
        ws_scheme = "ws"
    elif scheme in {"https", "wss"}:
        ws_scheme = "wss"
    else:
        raise ValueError("websocket_url must use http(s):// or ws(s):// scheme")

    path = parsed.path.rstrip("/")
    if path.endswith("/websocket"):
        resolved_path = path
    elif not path:
        resolved_path = "/websocket"
    else:
        resolved_path = f"{path}/websocket"

    return urlunsplit((ws_scheme, parsed.netloc, resolved_path, "", ""))


def _rpc_graphql_url(url: str) -> str:
    parsed = urlsplit(url)
    if not parsed.scheme:
        parsed = urlsplit(f"http://{url}")
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise ValueError("node_url must use http(s):// scheme")

    path = parsed.path.rstrip("/")
    if path.endswith("/graphql"):
        resolved_path = path
    elif not path:
        resolved_path = "/graphql"
    else:
        resolved_path = f"{path}/graphql"

    return urlunsplit((scheme, parsed.netloc, resolved_path, "", ""))


def _quote_cometbft_query_value(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"


def _build_cometbft_event_query(contract: str, event: str) -> str:
    return (
        "tm.event='Tx' "
        f"AND {event}.contract={_quote_cometbft_query_value(contract)}"
    )


def _decode_ws_tx_execution(payload: dict[str, Any]) -> dict[str, Any] | None:
    tx_result = (
        payload.get("result", {})
        .get("data", {})
        .get("value", {})
        .get("TxResult", {})
        .get("result", {})
    )
    encoded = tx_result.get("data") if isinstance(tx_result, dict) else None
    if not isinstance(encoded, str) or not encoded:
        return None
    try:
        decoded = tr.decode_str(encoded)
    except Exception:
        return None
    try:
        parsed = ast.literal_eval(decoded)
    except Exception:
        parsed = None
    if isinstance(parsed, dict):
        return parsed
    try:
        loaded = json.loads(decoded)
    except json.JSONDecodeError:
        return None
    return loaded if isinstance(loaded, dict) else None


def _ws_tx_metadata(
    payload: dict[str, Any],
) -> tuple[str | None, int | None, int | None]:
    ws_result = payload.get("result", {})
    value = ws_result.get("data", {}).get("value", {})
    tx_result = value.get("TxResult", {})
    result = tx_result.get("result", {})
    execution = _decode_ws_tx_execution(payload)
    tx_hash = None
    ws_events = ws_result.get("events")
    if isinstance(ws_events, dict):
        tx_hash_values = ws_events.get("tx.hash")
        if isinstance(tx_hash_values, list) and tx_hash_values:
            first_tx_hash = tx_hash_values[0]
            if isinstance(first_tx_hash, str):
                tx_hash = first_tx_hash
        elif isinstance(tx_hash_values, str):
            tx_hash = tx_hash_values
    if not isinstance(tx_hash, str):
        tx_hash = result.get("hash")
    if not isinstance(tx_hash, str):
        tx_hash = tx_result.get("hash")
    if not isinstance(tx_hash, str):
        tx_hash = execution.get("hash") if isinstance(execution, dict) else None
    block_height = _coerce_int(tx_result.get("height") or value.get("height"))
    tx_index = _coerce_int(tx_result.get("index"))
    return tx_hash if isinstance(tx_hash, str) else None, block_height, tx_index


def _extract_matching_live_events(
    payload: dict[str, Any],
    *,
    contract: str,
    event: str,
) -> list[LiveEvent]:
    execution = _decode_ws_tx_execution(payload)
    if not isinstance(execution, dict):
        return []
    tx_hash, block_height, tx_index = _ws_tx_metadata(payload)
    events = execution.get("events")
    if not isinstance(events, list):
        return []

    matched: list[LiveEvent] = []
    for event_index, item in enumerate(events):
        if not isinstance(item, dict):
            continue
        item_contract = str(item.get("contract", ""))
        item_event = str(item.get("event", "ContractEvent"))
        if item_contract != contract or item_event != event:
            continue

        data_indexed = item.get("data_indexed")
        normalized_indexed = (
            dict(data_indexed) if isinstance(data_indexed, dict) else None
        )
        data = item.get("data")
        normalized_data = dict(data) if isinstance(data, dict) else None

        matched.append(
            LiveEvent(
                tx_hash=tx_hash,
                block_height=block_height,
                tx_index=tx_index,
                event_index=event_index,
                contract=item_contract,
                event=item_event,
                signer=item.get("signer"),
                caller=item.get("caller"),
                data_indexed=normalized_indexed,
                data=normalized_data,
                raw=dict(item),
            )
        )
    return matched


def _graphql_event_node_to_dict(node: dict[str, Any]) -> dict[str, Any]:
    transaction = node.get("transactionByTxHash")
    block_height = None
    if isinstance(transaction, dict):
        block_height = _coerce_int(transaction.get("blockHeight"))

    return {
        "id": _coerce_int(node.get("id")),
        "tx_hash": node.get("txHash"),
        "block_height": block_height,
        "tx_index": None,
        "event_index": None,
        "contract": node.get("contract"),
        "event": node.get("event"),
        "signer": node.get("signer"),
        "caller": node.get("caller"),
        "data_indexed": node.get("dataIndexed"),
        "data": node.get("data"),
        "created": node.get("created"),
        "raw": dict(node),
    }


def _validate_xian_wallet(wallet: Any) -> None:
    public_key = getattr(wallet, "public_key", None)
    sign_msg = getattr(wallet, "sign_msg", None)
    if (
        not callable(sign_msg)
        or not isinstance(public_key, str)
        or not Wallet.is_valid_key(public_key)
    ):
        raise TypeError(
            "wallet must expose an Ed25519 Xian account; use xian_py.Wallet "
            "or an equivalent signer with an Ed25519 public_key"
        )
