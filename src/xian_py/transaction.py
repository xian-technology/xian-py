"""
Transaction module for interacting with the Xian blockchain.

This module provides both async and sync versions of all functions:
- Async functions have the `_async` suffix (e.g., get_nonce_async)
- Sync functions have no suffix (e.g., get_nonce)

Both versions are exported to allow users to choose based on their needs.
"""

import hashlib
import json
from asyncio import get_running_loop, sleep
from base64 import b64decode
from copy import deepcopy
from typing import Any

import aiohttp
from xian_runtime_types.encoding import encode

from xian_py.async_utils import sync_wrapper
from xian_py.exception import (
    AbciError,
    RpcError,
    SimulationError,
    TransactionError,
    TransportError,
    TxTimeoutError,
    XianException,
)
from xian_py.formating import check_format_of_payload, format_dictionary
from xian_py.wallet import Wallet


def decode_str(encoded_data: str) -> str:
    return b64decode(encoded_data).decode("utf-8")


def decode_dict(encoded_dict: str) -> dict:
    decoded_data = decode_str(encoded_dict)
    decoded_tx = bytes.fromhex(decoded_data).decode("utf-8")
    return json.loads(decoded_tx)


async def request_json_async(
    method: str,
    url: str,
    *,
    session: aiohttp.ClientSession | None = None,
    raise_for_status: bool = False,
    request_kwargs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if session is None:
        async with aiohttp.ClientSession() as owned_session:
            return await request_json_async(
                method,
                url,
                session=owned_session,
                raise_for_status=raise_for_status,
                request_kwargs=request_kwargs,
            )

    request_kwargs = dict(request_kwargs or {})
    requester = getattr(session, "request", None)
    if requester is not None:
        request_context = requester(method, url, **request_kwargs)
    else:
        request_context = getattr(session, method.lower())(
            url, **request_kwargs
        )

    try:
        async with request_context as response:
            if raise_for_status and hasattr(response, "raise_for_status"):
                response.raise_for_status()
            return await response.json()
    except XianException:
        raise
    except Exception as exc:
        raise TransportError(exc) from exc


async def abci_query_async(
    node_url: str,
    path: str,
    *,
    session: aiohttp.ClientSession | None = None,
) -> dict[str, Any]:
    data = await request_json_async(
        "POST",
        f'{node_url}/abci_query?path="{path}"',
        session=session,
        raise_for_status=True,
    )
    if "error" in data:
        raise RpcError(
            data["error"].get("data")
            or data["error"].get("message")
            or "RPC error",
            details=data["error"],
        )

    response = data.get("result", {}).get("response", {})
    if response.get("code", 0) != 0:
        raise AbciError(
            response.get("log") or "ABCI query failed",
            details={"path": path, "response": response},
        )

    return data


async def get_nonce_async(
    node_url: str,
    address: str,
    *,
    session: aiohttp.ClientSession | None = None,
) -> int:
    """
    Return next nonce for given address
    :param node_url: Node URL in format 'http://<IP>:<Port>'
    :param address: Wallet address for which the nonce will be returned
    :return: Next unused nonce
    """
    try:
        data = await abci_query_async(
            node_url,
            f"/get_next_nonce/{address}",
            session=session,
        )
    except XianException:
        raise
    except Exception as e:
        raise XianException(e) from e

    value = data["result"]["response"]["value"]

    # Data is None
    if value == "AA==":
        return 0

    nonce = decode_str(value)
    return int(nonce)


# Sync wrapper for backward compatibility
get_nonce = sync_wrapper(get_nonce_async)


async def get_tx_async(
    node_url: str,
    tx_hash: str,
    decode: bool = True,
    *,
    session: aiohttp.ClientSession | None = None,
) -> dict:
    """
    Return transaction either with encoded or decoded content
    :param node_url: Node URL in format 'http://<IP>:<Port>'
    :param tx_hash: Hash of transaction that gets retrieved
    :param decode: If TRUE, returned JSON data will be decoded
    :return: Transaction data in JSON
    """
    try:
        data = await request_json_async(
            "GET",
            f"{node_url}/tx?hash=0x{tx_hash}",
            session=session,
        )
    except XianException:
        raise
    except Exception as e:
        raise XianException(e) from e

    if decode and "result" in data:
        decoded = decode_dict(data["result"]["tx"])
        data["result"]["tx"] = decoded

        if data["result"]["tx_result"]["data"] is not None:
            decoded = decode_str(data["result"]["tx_result"]["data"])
            data["result"]["tx_result"]["data"] = json.loads(decoded)

    return data


# Sync wrapper for backward compatibility
get_tx = sync_wrapper(get_tx_async)


def canonical_json(value: dict) -> str:
    return json.dumps(
        format_dictionary(deepcopy(value)),
        ensure_ascii=False,
        separators=(",", ":"),
    )


def normalize_transaction_payload(payload: dict) -> dict:
    payload = format_dictionary(deepcopy(payload))
    if "kwargs" in payload:
        payload["kwargs"] = json.loads(encode(payload["kwargs"]))
        payload = format_dictionary(payload)
    return payload


async def simulate_tx_async(
    node_url: str,
    payload: dict,
    *,
    session: aiohttp.ClientSession | None = None,
) -> dict:
    """Estimate the amount of chi a tx will cost"""
    encoded = encode(payload).encode().hex()

    try:
        data = await abci_query_async(
            node_url,
            f"/simulate_tx/{encoded}",
            session=session,
        )
    except AbciError as e:
        raise SimulationError(str(e), cause=e, details=e.details) from e
    except XianException:
        raise
    except Exception as e:
        raise XianException(e) from e

    res = data["result"]["response"]

    if res["code"] != 0:
        raise SimulationError(res["log"], details=res)

    return json.loads(decode_str(res["value"]))


# Sync wrapper for backward compatibility
simulate_tx = sync_wrapper(simulate_tx_async)


async def get_status_async(
    node_url: str,
    *,
    session: aiohttp.ClientSession | None = None,
) -> dict[str, Any]:
    return await request_json_async(
        "GET",
        f"{node_url}/status",
        session=session,
    )


async def get_block_async(
    node_url: str,
    height: int,
    *,
    session: aiohttp.ClientSession | None = None,
) -> dict[str, Any]:
    return await request_json_async(
        "GET",
        f"{node_url}/block?height={height}",
        session=session,
    )


async def get_block_results_async(
    node_url: str,
    height: int,
    *,
    session: aiohttp.ClientSession | None = None,
) -> dict[str, Any]:
    return await request_json_async(
        "GET",
        f"{node_url}/block_results?height={height}",
        session=session,
    )


def create_tx(payload: dict, wallet: Wallet) -> dict:
    """
    Create offline transaction that can be broadcast
    :param payload: Transaction payload with following keys:
        chain_id: Network ID
        contract: Contract name to be executed
        function: Function name to be executed
        kwargs: Arguments for function
        nonce: Unique continuous number
        sender: Wallet address of sender
        chi: Max amount of chi to use
    :param wallet: Wallet object with public and private key
    :return: Encoded transaction data
    """
    payload = normalize_transaction_payload(payload)
    if not check_format_of_payload(payload):
        raise TransactionError("Invalid payload provided")
    canonical_payload = canonical_json(payload)

    tx = {
        "payload": payload,
        "metadata": {"signature": wallet.sign_msg(canonical_payload)},
    }

    return json.loads(canonical_json(tx))


async def broadcast_tx_commit_async(
    node_url: str,
    tx: dict,
    *,
    session: aiohttp.ClientSession | None = None,
) -> dict:
    """
    DO NOT USE IN PRODUCTION - ONLY FOR TESTS IN DEVELOPMENT!
    Submits a transaction to be included in the blockchain and
    returns the response from CheckTx and DeliverTx.
    :param node_url: Node URL in format 'http://<IP>:<Port>'
    :param tx: Transaction data in JSON format (dict)
    :return: JSON data with tx hash, CheckTx and DeliverTx results
    """
    payload = json.dumps(tx).encode().hex()

    try:
        data = await request_json_async(
            "POST",
            f"{node_url}/broadcast_tx_commit",
            session=session,
            request_kwargs={"data": {"tx": f'"{payload}"'}},
        )
    except XianException:
        raise
    except Exception as e:
        raise XianException(e) from e

    return data


# Sync wrapper for backward compatibility
broadcast_tx_commit = sync_wrapper(broadcast_tx_commit_async)


async def broadcast_tx_wait_async(
    node_url: str,
    tx: dict,
    *,
    session: aiohttp.ClientSession | None = None,
) -> dict:
    """
    Submits a transaction to be included in the blockchain and returns
    the response from CheckTx. Does not wait for DeliverTx result.
    :param node_url: Node URL in format 'http://<IP>:<Port>'
    :param tx: Transaction data in JSON format (dict)
    :return: JSON data with tx hash and CheckTx result
    """
    payload = json.dumps(tx).encode().hex()

    try:
        data = await request_json_async(
            "POST",
            f"{node_url}/broadcast_tx_sync",
            session=session,
            request_kwargs={"data": {"tx": f'"{payload}"'}},
        )
    except XianException:
        raise
    except Exception as e:
        raise XianException(e) from e

    return data


# Sync wrapper for backward compatibility
broadcast_tx_wait = sync_wrapper(broadcast_tx_wait_async)


async def broadcast_tx_nowait_async(
    node_url: str,
    tx: dict,
    *,
    session: aiohttp.ClientSession | None = None,
):
    """
    Submits a transaction to be included in the blockchain and returns
    immediately. Does not wait for CheckTx or DeliverTx results.

    This is the fastest broadcast method but provides no confirmation
    that the transaction was accepted or processed.

    :param node_url: Node URL in format 'http://<IP>:<Port>'
    :param tx: Transaction data in JSON format (dict)
    """
    payload = json.dumps(tx).encode().hex()

    try:
        return await request_json_async(
            "POST",
            f"{node_url}/broadcast_tx_async",
            session=session,
            raise_for_status=True,
            request_kwargs={"data": {"tx": f'"{payload}"'}},
        )
    except XianException:
        raise
    except Exception as e:
        raise XianException(e) from e


# Sync wrapper for backward compatibility
broadcast_tx_nowait = sync_wrapper(broadcast_tx_nowait_async)


def _hash_block_tx(block_tx: str) -> str:
    encoded = b64decode(block_tx).decode("utf-8")
    return hashlib.sha256(bytes.fromhex(encoded)).hexdigest().upper()


def _decode_block_result_data(value: Any) -> Any:
    if value in (None, ""):
        return value
    try:
        decoded = decode_str(value)
    except Exception:
        return value
    try:
        return json.loads(decoded)
    except json.JSONDecodeError:
        return decoded


async def _lookup_tx_in_recent_blocks_async(
    node_url: str,
    tx_hash: str,
    *,
    start_height: int,
    end_height: int,
    session: aiohttp.ClientSession | None = None,
) -> dict[str, Any] | None:
    target_hash = tx_hash.upper()
    for height in range(max(1, start_height), end_height + 1):
        block = await get_block_async(node_url, height, session=session)
        block_txs = (
            block.get("result", {}).get("block", {}).get("data", {}).get("txs")
            or []
        )
        if not block_txs:
            continue

        for index, block_tx in enumerate(block_txs):
            if _hash_block_tx(block_tx) != target_hash:
                continue

            block_results = await get_block_results_async(
                node_url,
                height,
                session=session,
            )
            txs_results = (
                block_results.get("result", {}).get("txs_results") or []
            )
            tx_result = (
                dict(txs_results[index])
                if index < len(txs_results)
                and isinstance(txs_results[index], dict)
                else {"code": 0, "data": None, "log": ""}
            )
            tx_result["data"] = _decode_block_result_data(tx_result.get("data"))
            return {
                "result": {
                    "hash": target_hash,
                    "height": str(height),
                    "index": index,
                    "tx": decode_dict(block_tx),
                    "tx_result": tx_result,
                }
            }
    return None


async def wait_for_tx_async(
    node_url: str,
    tx_hash: str,
    *,
    timeout_seconds: float = 30.0,
    poll_interval_seconds: float = 0.25,
    session: aiohttp.ClientSession | None = None,
) -> dict:
    """
    Poll the node until a transaction becomes available or timeout expires.
    """
    deadline = get_running_loop().time() + timeout_seconds
    last_error: str | None = None
    last_scanned_height = 0
    initial_block_scan_window = 8

    while True:
        latest_height = None
        try:
            data = await get_tx_async(
                node_url,
                tx_hash,
                session=session,
            )
        except TransportError as exc:
            last_error = str(exc)
        else:
            if "error" not in data:
                return data

            last_error = data["error"].get("data") or data["error"].get(
                "message"
            )
            try:
                status = await get_status_async(node_url, session=session)
                latest_height_raw = (
                    status.get("result", {})
                    .get("sync_info", {})
                    .get("latest_block_height")
                )
                latest_height = (
                    int(latest_height_raw)
                    if latest_height_raw is not None
                    else None
                )
            except TransportError as exc:
                last_error = str(exc)
            except Exception:
                latest_height = None

        if latest_height is not None:
            scan_from = (
                max(1, latest_height - initial_block_scan_window + 1)
                if last_scanned_height == 0
                else last_scanned_height + 1
            )
            if scan_from <= latest_height:
                try:
                    fallback = await _lookup_tx_in_recent_blocks_async(
                        node_url,
                        tx_hash,
                        start_height=scan_from,
                        end_height=latest_height,
                        session=session,
                    )
                except TransportError as exc:
                    last_error = str(exc)
                else:
                    if fallback is not None:
                        return fallback
                    last_scanned_height = latest_height

        if get_running_loop().time() >= deadline:
            raise TxTimeoutError(
                f"Timed out waiting for transaction {tx_hash}: {last_error or 'not found'}"
            )

        await sleep(poll_interval_seconds)


wait_for_tx = sync_wrapper(wait_for_tx_async)
