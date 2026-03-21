"""
Transaction module for interacting with the Xian blockchain.

This module provides both async and sync versions of all functions:
- Async functions have the `_async` suffix (e.g., get_nonce_async)
- Sync functions have no suffix (e.g., get_nonce)

Both versions are exported to allow users to choose based on their needs.
"""

import json
from asyncio import get_running_loop, sleep
from base64 import b64decode
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
) -> dict[str, Any]:
    if session is None:
        async with aiohttp.ClientSession() as owned_session:
            return await request_json_async(
                method,
                url,
                session=owned_session,
                raise_for_status=raise_for_status,
            )

    requester = getattr(session, "request", None)
    if requester is not None:
        request_context = requester(method, url)
    else:
        request_context = getattr(session, method.lower())(url)

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
            data["error"].get("data") or data["error"].get("message") or "RPC error",
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


async def simulate_tx_async(
    node_url: str,
    payload: dict,
    *,
    session: aiohttp.ClientSession | None = None,
) -> dict:
    """Estimate the amount of stamps a tx will cost"""
    encoded = json.dumps(payload).encode().hex()

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
        stamps: Max amount of stamps to use
    :param wallet: Wallet object with public and private key
    :return: Encoded transaction data
    """
    payload = format_dictionary(payload)
    if not check_format_of_payload(payload):
        raise TransactionError("Invalid payload provided")

    tx = {
        "payload": payload,
        "metadata": {"signature": wallet.sign_msg(json.dumps(payload))},
    }

    tx = encode(format_dictionary(tx))
    return json.loads(tx)


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
            f'{node_url}/broadcast_tx_commit?tx="{payload}"',
            session=session,
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
            f'{node_url}/broadcast_tx_sync?tx="{payload}"',
            session=session,
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
            f'{node_url}/broadcast_tx_async?tx="{payload}"',
            session=session,
            raise_for_status=True,
        )
    except XianException:
        raise
    except Exception as e:
        raise XianException(e) from e


# Sync wrapper for backward compatibility
broadcast_tx_nowait = sync_wrapper(broadcast_tx_nowait_async)


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

    while True:
        data = await get_tx_async(
            node_url,
            tx_hash,
            session=session,
        )
        if "error" not in data:
            return data

        last_error = data["error"].get("data") or data["error"].get("message")
        if get_running_loop().time() >= deadline:
            raise TxTimeoutError(
                f"Timed out waiting for transaction {tx_hash}: {last_error or 'not found'}"
            )

        await sleep(poll_interval_seconds)


wait_for_tx = sync_wrapper(wait_for_tx_async)
