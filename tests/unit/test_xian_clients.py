import asyncio
import base64
from unittest.mock import ANY, AsyncMock, patch

import pytest
from xian_runtime_types.decimal import ContractingDecimal

import xian_py.transaction as tr
from xian_py.decompiler import ContractDecompiler
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

    async def run_send_tx() -> dict:
        try:
            return await client.send_tx(
                "currency",
                "transfer",
                {"amount": 1, "to": wallet.public_key},
            )
        finally:
            await client.close()

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
                    result = asyncio.run(run_send_tx())

    get_nonce_async.assert_awaited_once_with(
        "http://node",
        wallet.public_key,
        session=ANY,
    )
    simulate_tx_async.assert_awaited_once()
    create_payload = create_tx.call_args.args[0]
    assert create_payload["chain_id"] == "xian-mainnet-1"
    assert create_payload["nonce"] == 11
    assert create_payload["stamps_supplied"] == 87
    broadcast_tx_wait_async.assert_awaited_once_with(
        "http://node",
        {"signed": True},
        session=ANY,
    )
    assert result["submitted"] is True
    assert result["accepted"] is True
    assert result["finalized"] is False
    assert result["tx_hash"] == "abc123"
    assert result["stamps_estimated"] == 77
    assert result["stamps_supplied"] == 87


def test_xian_async_send_tx_reserves_nonces_locally_for_concurrent_calls() -> None:
    wallet = Wallet()
    client = XianAsync("http://node", chain_id="xian-1", wallet=wallet)
    observed_nonces: list[int] = []

    def _capture_tx(payload: dict, wallet: Wallet) -> dict:
        observed_nonces.append(payload["nonce"])
        return {"signed": payload["nonce"]}

    async def run_sends() -> None:
        try:
            await asyncio.gather(
                client.send_tx(
                    "currency",
                    "transfer",
                    {"amount": 1, "to": wallet.public_key},
                    stamps=100,
                ),
                client.send_tx(
                    "currency",
                    "transfer",
                    {"amount": 2, "to": wallet.public_key},
                    stamps=100,
                ),
            )
        finally:
            await client.close()

    with patch.object(
        tr, "get_nonce_async", AsyncMock(return_value=7)
    ) as get_nonce_async:
        with patch.object(tr, "create_tx", side_effect=_capture_tx):
            with patch.object(
                tr,
                "broadcast_tx_wait_async",
                AsyncMock(return_value={"result": {"code": 0, "hash": "ok"}}),
            ):
                asyncio.run(run_sends())

    get_nonce_async.assert_awaited_once_with(
        "http://node",
        wallet.public_key,
        session=ANY,
    )
    assert sorted(observed_nonces) == [7, 8]


def test_xian_async_send_tx_invalidates_reserved_nonce_after_checktx_failure() -> None:
    wallet = Wallet()
    client = XianAsync("http://node", chain_id="xian-1", wallet=wallet)
    observed_nonces: list[int] = []

    def _capture_tx(payload: dict, wallet: Wallet) -> dict:
        observed_nonces.append(payload["nonce"])
        return {"signed": payload["nonce"]}

    async def run_sends() -> None:
        try:
            failed = await client.send_tx(
                "currency",
                "transfer",
                {"amount": 1, "to": wallet.public_key},
                stamps=100,
            )
            succeeded = await client.send_tx(
                "currency",
                "transfer",
                {"amount": 1, "to": wallet.public_key},
                stamps=100,
            )
            return failed, succeeded
        finally:
            await client.close()

    with patch.object(
        tr, "get_nonce_async", AsyncMock(side_effect=[7, 7])
    ) as get_nonce_async:
        with patch.object(tr, "create_tx", side_effect=_capture_tx):
            with patch.object(
                tr,
                "broadcast_tx_wait_async",
                AsyncMock(
                    side_effect=[
                        {"result": {"code": 7, "log": "bad nonce", "hash": "bad"}},
                        {"result": {"code": 0, "hash": "good"}},
                    ]
                ),
            ):
                failed, succeeded = asyncio.run(run_sends())

    assert failed["accepted"] is False
    assert failed["submitted"] is True
    assert succeeded["accepted"] is True
    assert observed_nonces == [7, 7]
    assert get_nonce_async.await_count == 2


def test_xian_async_send_tx_can_wait_for_finalized_receipt() -> None:
    wallet = Wallet()
    client = XianAsync("http://node", chain_id="xian-1", wallet=wallet)

    async def run_send() -> dict:
        try:
            return await client.send_tx(
                "currency",
                "transfer",
                {"amount": 1, "to": wallet.public_key},
                stamps=100,
                wait_for_tx=True,
                timeout_seconds=1.0,
                poll_interval_seconds=0.0,
            )
        finally:
            await client.close()

    with patch.object(
        tr,
        "get_nonce_async",
        AsyncMock(return_value=11),
    ):
        with patch.object(
        tr,
        "broadcast_tx_wait_async",
        AsyncMock(return_value={"result": {"code": 0, "hash": "abc123"}}),
        ):
            with patch.object(
                tr,
                "get_tx_async",
                AsyncMock(
                    return_value={
                        "result": {
                            "tx": {"payload": {"contract": "currency"}},
                            "tx_result": {"code": 0, "data": {"result": "ok"}},
                        }
                    }
                ),
            ):
                result = asyncio.run(run_send())

    assert result["accepted"] is True
    assert result["submitted"] is True
    assert result["finalized"] is True
    assert result["receipt"]["success"] is True


def test_xian_async_send_tx_async_mode_reports_submission_without_checktx() -> None:
    wallet = Wallet()
    client = XianAsync("http://node", chain_id="xian-1", wallet=wallet)

    async def run_send() -> dict:
        try:
            return await client.send_tx(
                "currency",
                "transfer",
                {"amount": 1, "to": wallet.public_key},
                stamps=100,
                mode="async",
            )
        finally:
            await client.close()

    with patch.object(
        tr,
        "get_nonce_async",
        AsyncMock(return_value=11),
    ):
        with patch.object(
            tr,
            "broadcast_tx_nowait_async",
            AsyncMock(return_value={"result": {"hash": "abc123"}}),
        ):
            result = asyncio.run(run_send())

    assert result["submitted"] is True
    assert result["accepted"] is None
    assert result["finalized"] is False
    assert result["tx_hash"] == "abc123"


def test_xian_async_get_balance_falls_back_to_abci_query() -> None:
    wallet = Wallet()
    client = XianAsync("http://node", chain_id="xian-1", wallet=wallet)
    client._session = _FakeSession(
        get_responses=[
            _FakeResponse(
                {
                    "result": {
                        "response": {
                            "value": _b64("12.5"),
                            "info": "decimal",
                        }
                    }
                },
            )
        ]
    )

    with patch.object(
        tr,
        "simulate_tx_async",
        AsyncMock(side_effect=RuntimeError("simulation unavailable")),
    ):
        balance = asyncio.run(client.get_balance())

    assert balance == ContractingDecimal("12.5")


def test_xian_async_get_tx_surfaces_error_payloads() -> None:
    client = XianAsync("http://node", chain_id="xian-1")

    with patch.object(
        tr,
        "get_tx_async",
        AsyncMock(
            return_value={
                "result": {
                    "tx_result": {
                        "code": 1,
                        "data": {"error": "boom"},
                    }
                }
            }
        ),
    ):

        async def run_get_tx() -> dict:
            try:
                return await client.get_tx("abc123")
            finally:
                await client.close()

        data = asyncio.run(run_get_tx())

    assert data["success"] is False
    assert data["message"] == "boom"


def test_xian_async_get_tx_exposes_transaction_and_execution() -> None:
    client = XianAsync("http://node", chain_id="xian-1")
    tx = {"payload": {"contract": "currency", "function": "transfer"}}
    execution = {"status": 0, "result": "ok", "stamps_used": 7}

    with patch.object(
        tr,
        "get_tx_async",
        AsyncMock(
            return_value={
                "result": {
                    "tx": tx,
                    "tx_result": {
                        "code": 0,
                        "data": execution,
                    },
                }
            }
        ),
    ):

        async def run_get_tx() -> dict:
            try:
                return await client.get_tx("abc123")
            finally:
                await client.close()

        data = asyncio.run(run_get_tx())

    assert data["success"] is True
    assert data["transaction"] == tx
    assert data["execution"] == execution


def test_xian_async_get_state_decodes_supported_value_shapes() -> None:
    wallet = Wallet()
    client = XianAsync("http://node", chain_id="xian-1", wallet=wallet)
    client._session = _FakeSession(
        get_responses=[
            _FakeResponse({"result": {"response": {"value": "AA=="}}}),
            _FakeResponse(
                {"result": {"response": {"value": _b64("15"), "info": "int"}}}
            ),
            _FakeResponse(
                {
                    "result": {
                        "response": {
                            "value": _b64("12.5"),
                            "info": "decimal",
                        }
                    }
                }
            ),
            _FakeResponse(
                {
                    "result": {
                        "response": {
                            "value": _b64('{"owner":"alice"}'),
                            "info": "dict",
                        }
                    }
                },
            ),
        ]
    )

    assert (
        asyncio.run(client.get_state("currency", "balances", "alice")) is None
    )
    assert asyncio.run(client.get_state("currency", "balances", "alice")) == 15
    assert asyncio.run(client.get_state("currency", "balances", "alice")) == (
        ContractingDecimal("12.5")
    )
    assert asyncio.run(client.get_state("currency", "balances", "alice")) == {
        "owner": "alice",
    }


def test_xian_async_send_preserves_decimal_precision() -> None:
    wallet = Wallet()
    client = XianAsync("http://node", chain_id="xian-1", wallet=wallet)

    with patch.object(
        client,
        "send_tx",
        AsyncMock(return_value={"success": True}),
    ) as send_tx:
        asyncio.run(
            client.send(
                "12345678901234567890.123456789012345678901234567890",
                wallet.public_key,
            )
        )

    kwargs = send_tx.await_args.args[2]
    assert kwargs["amount"] == ContractingDecimal(
        "12345678901234567890.123456789012345678901234567890"
    )


def test_xian_async_approve_preserves_decimal_precision() -> None:
    wallet = Wallet()
    client = XianAsync("http://node", chain_id="xian-1", wallet=wallet)

    with patch.object(
        client,
        "send_tx",
        AsyncMock(return_value={"success": True}),
    ) as send_tx:
        asyncio.run(
            client.approve(
                "dex",
                amount="12345678901234567890.123456789012345678901234567890",
            )
        )

    kwargs = send_tx.await_args.args[2]
    assert kwargs["amount"] == ContractingDecimal(
        "12345678901234567890.123456789012345678901234567890"
    )


def test_contract_decompiler_supports_python_314_ast() -> None:
    source = """
balances = Hash(default_value=0, contract='con_test', name='balances')

@__export('con_test')
def foo() -> str:
    return decimal('1.25')
"""

    output = ContractDecompiler().decompile(source)

    assert "def foo() ->str:" in output or "def foo() -> str:" in output
    assert (
        'return decimal("1.25")' in output
        or "return decimal('1.25')" in output
    )


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
