import asyncio
import base64
from unittest.mock import AsyncMock, patch

import pytest

import xian_py.transaction as tr
from xian_py.wallet import Wallet
from xian_py.xian import Xian
from xian_py.xian_async import XianAsync


def _b64(value: str) -> str:
    return base64.b64encode(value.encode("utf-8")).decode("utf-8")


class _FakeResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self) -> dict:
        return self.payload


class _FakeSession:
    def __init__(
        self,
        *,
        get_responses: list[_FakeResponse] | None = None,
        post_responses: list[_FakeResponse] | None = None,
    ):
        self.get_responses = list(get_responses or [])
        self.post_responses = list(post_responses or [])
        self.closed = False

    def get(self, url: str) -> _FakeResponse:
        return self.get_responses.pop(0)

    def post(self, url: str) -> _FakeResponse:
        return self.post_responses.pop(0)

    async def close(self) -> None:
        self.closed = True


def test_xian_async_send_tx_populates_chain_id_nonce_and_stamps() -> None:
    wallet = Wallet()
    client = XianAsync("http://node", wallet=wallet)
    client.get_chain_id = AsyncMock(return_value="xian-mainnet-1")

    with patch.object(
        tr, "get_nonce_async", AsyncMock(return_value=11)
    ) as get_nonce_async:
        with patch.object(
            tr,
            "simulate_tx_async",
            AsyncMock(return_value={"stamps_used": 77}),
        ) as simulate_tx_async:
            with patch.object(
                tr,
                "create_tx",
                return_value={"signed": True},
            ) as create_tx:
                with patch.object(
                    tr,
                    "broadcast_tx_wait_async",
                    AsyncMock(
                        return_value={"result": {"code": 0, "hash": "abc123"}}
                    ),
                ) as broadcast_tx_wait_async:
                    result = asyncio.run(
                        client.send_tx(
                            "currency",
                            "transfer",
                            {"amount": 1, "to": wallet.public_key},
                        )
                    )

    get_nonce_async.assert_awaited_once_with("http://node", wallet.public_key)
    simulate_tx_async.assert_awaited_once()
    create_payload = create_tx.call_args.args[0]
    assert create_payload["chain_id"] == "xian-mainnet-1"
    assert create_payload["nonce"] == 11
    assert create_payload["stamps_supplied"] == 77
    broadcast_tx_wait_async.assert_awaited_once_with(
        "http://node",
        {"signed": True},
    )
    assert result["success"] is True
    assert result["tx_hash"] == "abc123"


def test_xian_async_get_balance_falls_back_to_abci_query() -> None:
    wallet = Wallet()
    client = XianAsync("http://node", chain_id="xian-1", wallet=wallet)
    client._session = _FakeSession(
        get_responses=[
            _FakeResponse(
                {"result": {"response": {"value": _b64("12.5")}}},
            )
        ]
    )

    with patch.object(
        tr,
        "simulate_tx_async",
        AsyncMock(side_effect=RuntimeError("simulation unavailable")),
    ):
        balance = asyncio.run(client.get_balance())

    assert balance == 12.5


def test_xian_async_get_state_decodes_supported_value_shapes() -> None:
    wallet = Wallet()
    client = XianAsync("http://node", chain_id="xian-1", wallet=wallet)
    client._session = _FakeSession(
        get_responses=[
            _FakeResponse({"result": {"response": {"value": "AA=="}}}),
            _FakeResponse({"result": {"response": {"value": _b64("15")}}}),
            _FakeResponse({"result": {"response": {"value": _b64("12.5")}}}),
            _FakeResponse(
                {"result": {"response": {"value": _b64("{'owner': 'alice'}")}}},
            ),
        ]
    )

    assert (
        asyncio.run(client.get_state("currency", "balances", "alice")) is None
    )
    assert asyncio.run(client.get_state("currency", "balances", "alice")) == 15
    assert (
        asyncio.run(client.get_state("currency", "balances", "alice")) == 12.5
    )
    assert asyncio.run(client.get_state("currency", "balances", "alice")) == {
        "owner": "alice",
    }


def test_xian_async_get_contract_clean_uses_decompiler() -> None:
    wallet = Wallet()
    client = XianAsync("http://node", chain_id="xian-1", wallet=wallet)
    client._session = _FakeSession(
        get_responses=[
            _FakeResponse(
                {"result": {"response": {"value": _b64("compiled-code")}}},
            )
        ]
    )

    with patch(
        "xian_py.xian_async.ContractDecompiler.decompile",
        return_value="clean-code",
    ) as decompile:
        contract = asyncio.run(client.get_contract("currency", clean=True))

    decompile.assert_called_once_with("compiled-code")
    assert contract == "clean-code"


def test_xian_async_get_approved_amount_falls_back_to_balances() -> None:
    wallet = Wallet()
    client = XianAsync("http://node", chain_id="xian-1", wallet=wallet)
    client.get_state = AsyncMock(side_effect=[None, 25])

    approved_amount = asyncio.run(client.get_approved_amount("dex"))

    assert approved_amount == 25
    assert client.get_state.await_args_list[0].args == (
        "currency",
        "approvals",
        wallet.public_key,
        "dex",
    )
    assert client.get_state.await_args_list[1].args == (
        "currency",
        "balances",
        wallet.public_key,
        "dex",
    )


def test_xian_async_get_nodes_returns_remote_ips() -> None:
    client = XianAsync("http://node", chain_id="xian-1")
    client._session = _FakeSession(
        post_responses=[
            _FakeResponse(
                {
                    "result": {
                        "peers": [
                            {"remote_ip": "10.0.0.1"},
                            {"remote_ip": "10.0.0.2"},
                        ]
                    }
                }
            )
        ]
    )

    assert asyncio.run(client.get_nodes()) == ["10.0.0.1", "10.0.0.2"]


def test_sync_client_delegates_and_closes_async_client() -> None:
    wallet = Wallet()
    client = Xian("http://node", chain_id="xian-1", wallet=wallet)
    client._async_client.get_balance = AsyncMock(return_value=42)
    client._async_client.close = AsyncMock()

    assert client.get_balance() == 42
    client._async_client.close.assert_awaited_once()


def test_sync_client_rejects_calls_inside_running_loop() -> None:
    client = Xian("http://node", chain_id="xian-1", wallet=Wallet())

    async def invoke() -> None:
        coroutine = client._async_client.get_balance()
        try:
            with pytest.raises(RuntimeError, match="Use XianAsync directly"):
                client._run_async(coroutine)
        finally:
            coroutine.close()

    asyncio.run(invoke())
