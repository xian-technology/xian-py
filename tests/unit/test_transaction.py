import asyncio
import base64
import hashlib
import json
from decimal import Decimal
from unittest.mock import patch

import aiohttp
import pytest
from xian_runtime_types.encoding import decode, encode

from xian_py.exception import TransportError, XianException
from xian_py.formating import format_dictionary
from xian_py.transaction import (
    create_tx,
    get_nonce_async,
    simulate_tx_async,
    wait_for_tx_async,
)
from xian_py.wallet import Wallet


def _b64(value: str) -> str:
    return base64.b64encode(value.encode("utf-8")).decode("utf-8")


class _FakeResponse:
    def __init__(self, payload: dict, *, error: Exception | None = None):
        self.payload = payload
        self.error = error

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self) -> dict:
        return self.payload

    def raise_for_status(self) -> None:
        if self.error is not None:
            raise self.error


class _FakeClientSession:
    def __init__(
        self,
        *,
        get_responses: list[_FakeResponse] | None = None,
        post_responses: list[_FakeResponse] | None = None,
    ):
        self.get_responses = list(get_responses or [])
        self.post_responses = list(post_responses or [])
        self.calls: list[tuple[str, str]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def get(self, url: str) -> _FakeResponse:
        self.calls.append(("get", url))
        return self.get_responses.pop(0)

    def post(self, url: str) -> _FakeResponse:
        self.calls.append(("post", url))
        return self.post_responses.pop(0)


def test_get_nonce_async_returns_zero_for_empty_response() -> None:
    fake_session = _FakeClientSession(
        post_responses=[
            _FakeResponse({"result": {"response": {"value": "AA=="}}}),
        ]
    )

    with patch(
        "xian_py.transaction.aiohttp.ClientSession", return_value=fake_session
    ):
        nonce = asyncio.run(get_nonce_async("http://node", "abc123"))

    assert nonce == 0
    assert fake_session.calls == [
        ("post", 'http://node/abci_query?path="/get_next_nonce/abc123"'),
    ]


def test_get_nonce_async_decodes_nonce_value() -> None:
    fake_session = _FakeClientSession(
        post_responses=[
            _FakeResponse({"result": {"response": {"value": _b64("7")}}}),
        ]
    )

    with patch(
        "xian_py.transaction.aiohttp.ClientSession", return_value=fake_session
    ):
        nonce = asyncio.run(get_nonce_async("http://node", "abc123"))

    assert nonce == 7


def test_simulate_tx_async_decodes_successful_response() -> None:
    payload = {"contract": "currency", "function": "transfer"}
    expected = {"chi_used": 42, "result": "ok"}
    fake_session = _FakeClientSession(
        post_responses=[
            _FakeResponse(
                {
                    "result": {
                        "response": {
                            "code": 0,
                            "value": _b64(json.dumps(expected)),
                        }
                    }
                }
            )
        ]
    )

    with patch(
        "xian_py.transaction.aiohttp.ClientSession", return_value=fake_session
    ):
        result = asyncio.run(simulate_tx_async("http://node", payload))

    assert result == expected


def test_simulate_tx_async_encodes_runtime_numeric_values() -> None:
    payload = {
        "contract": "currency",
        "function": "transfer",
        "kwargs": {"amount": Decimal("12.5")},
    }
    fake_session = _FakeClientSession(
        post_responses=[
            _FakeResponse(
                {
                    "result": {
                        "response": {
                            "code": 0,
                            "value": _b64(json.dumps({"chi_used": 1})),
                        }
                    }
                }
            )
        ]
    )

    with patch(
        "xian_py.transaction.aiohttp.ClientSession", return_value=fake_session
    ):
        asyncio.run(simulate_tx_async("http://node", payload))

    method, url = fake_session.calls[0]
    assert method == "post"
    encoded_payload = url.split("/simulate_tx/", 1)[1].split('"', 1)[0]
    decoded_payload = json.loads(bytes.fromhex(encoded_payload).decode("utf-8"))
    assert decoded_payload["kwargs"]["amount"] == {"__fixed__": "12.5"}


def test_simulate_tx_async_wraps_error_response() -> None:
    fake_session = _FakeClientSession(
        post_responses=[
            _FakeResponse(
                {
                    "result": {
                        "response": {
                            "code": 1,
                            "log": "simulation failed",
                            "value": None,
                        }
                    }
                }
            )
        ]
    )

    with patch(
        "xian_py.transaction.aiohttp.ClientSession", return_value=fake_session
    ):
        with pytest.raises(XianException, match="simulation failed"):
            asyncio.run(
                simulate_tx_async(
                    "http://node",
                    {"contract": "currency", "function": "transfer"},
                )
            )


def test_get_nonce_async_wraps_http_errors() -> None:
    fake_session = _FakeClientSession(
        post_responses=[
            _FakeResponse(
                {},
                error=aiohttp.ClientConnectionError("boom"),
            )
        ]
    )

    with patch(
        "xian_py.transaction.aiohttp.ClientSession", return_value=fake_session
    ):
        with pytest.raises(XianException):
            asyncio.run(get_nonce_async("http://node", "abc123"))


def test_create_tx_formats_payload_and_signs_it() -> None:
    wallet = Wallet()
    payload = {
        "sender": wallet.public_key,
        "nonce": 1,
        "chi_supplied": 25,
        "contract": "currency",
        "function": "transfer",
        "kwargs": {"to": wallet.public_key, "amount": 5},
        "chain_id": "xian-local-1",
    }

    tx = create_tx(payload, wallet)

    expected_payload = format_dictionary(payload)
    canonical_payload = encode(decode(encode(expected_payload)))
    signature = tx["metadata"]["signature"]

    assert tx["payload"] == expected_payload
    assert wallet.verify_msg(canonical_payload, signature) is True
    assert wallet.verify_msg(json.dumps(expected_payload), signature) is False


def test_create_tx_rejects_invalid_payload() -> None:
    wallet = Wallet()

    with pytest.raises(XianException, match="Invalid payload provided"):
        create_tx({"contract": "currency"}, wallet)


def test_wait_for_tx_async_returns_decoded_transaction_once_found() -> None:
    fake_session = _FakeClientSession(
        get_responses=[
            _FakeResponse(
                {"error": {"message": "not found", "data": "missing"}}
            ),
            _FakeResponse(
                {
                    "result": {
                        "sync_info": {
                            "latest_block_height": "0",
                        }
                    }
                }
            ),
            _FakeResponse(
                {
                    "result": {
                        "tx": _b64(
                            json.dumps(
                                {
                                    "payload": {
                                        "contract": "currency",
                                        "function": "transfer",
                                    }
                                }
                            )
                            .encode("utf-8")
                            .hex()
                        ),
                        "tx_result": {
                            "data": _b64(
                                json.dumps({"status": 0, "result": "ok"})
                            ),
                        },
                    }
                }
            ),
        ]
    )

    with patch(
        "xian_py.transaction.aiohttp.ClientSession", return_value=fake_session
    ):
        result = asyncio.run(
            wait_for_tx_async(
                "http://node",
                "abc123",
                timeout_seconds=1.0,
                poll_interval_seconds=0.0,
            )
        )

    assert result["result"]["tx"]["payload"]["function"] == "transfer"
    assert result["result"]["tx_result"]["data"]["result"] == "ok"


def test_wait_for_tx_async_retries_transient_transport_errors() -> None:
    tx_payload = {
        "payload": {
            "contract": "currency",
            "function": "transfer",
            "kwargs": {"amount": 1, "to": "bob"},
        }
    }

    with patch(
        "xian_py.transaction.get_tx_async",
        side_effect=[
            TransportError("connection reset by peer"),
            {
                "result": {
                    "tx": tx_payload,
                    "tx_result": {
                        "code": 0,
                        "data": {"status": 0, "result": "ok"},
                    },
                }
            },
        ],
    ) as get_tx_async:
        result = asyncio.run(
            wait_for_tx_async(
                "http://node",
                "abc123",
                timeout_seconds=1.0,
                poll_interval_seconds=0.0,
            )
        )

    assert result["result"]["tx"]["payload"]["function"] == "transfer"
    assert result["result"]["tx_result"]["data"]["result"] == "ok"
    assert get_tx_async.await_count == 2


def test_wait_for_tx_async_falls_back_to_recent_block_scan() -> None:
    tx_payload = {
        "payload": {
            "contract": "currency",
            "function": "transfer",
            "kwargs": {"amount": 1, "to": "bob"},
        }
    }
    tx_hex = json.dumps(tx_payload).encode("utf-8").hex()
    block_tx = _b64(tx_hex)
    tx_hash = hashlib.sha256(bytes.fromhex(tx_hex)).hexdigest().upper()

    fake_session = _FakeClientSession(
        get_responses=[
            _FakeResponse(
                {"error": {"message": "not found", "data": "missing"}}
            ),
            _FakeResponse(
                {
                    "result": {
                        "sync_info": {
                            "latest_block_height": "5",
                        }
                    }
                }
            ),
            _FakeResponse(
                {
                    "result": {
                        "block": {
                            "data": {
                                "txs": [block_tx],
                            }
                        }
                    }
                }
            ),
            _FakeResponse(
                {
                    "result": {
                        "txs_results": [
                            {
                                "code": 0,
                                "data": _b64(
                                    json.dumps({"status": 0, "result": "ok"})
                                ),
                                "log": "",
                            }
                        ]
                    }
                }
            ),
        ]
    )

    with patch(
        "xian_py.transaction.aiohttp.ClientSession", return_value=fake_session
    ):
        result = asyncio.run(
            wait_for_tx_async(
                "http://node",
                tx_hash,
                timeout_seconds=1.0,
                poll_interval_seconds=0.0,
            )
        )

    assert result["result"]["hash"] == tx_hash
    assert result["result"]["height"] == "1"
    assert result["result"]["tx"]["payload"]["kwargs"]["to"] == "bob"
    assert result["result"]["tx_result"]["data"]["result"] == "ok"
    assert fake_session.calls == [
        ("get", f"http://node/tx?hash=0x{tx_hash}"),
        ("get", "http://node/status"),
        ("get", "http://node/block?height=1"),
        ("get", "http://node/block_results?height=1"),
    ]
