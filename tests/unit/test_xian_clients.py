import asyncio
import base64
from unittest.mock import ANY, AsyncMock, patch

import pytest
from xian_runtime_types.decimal import ContractingDecimal

import xian_py.transaction as tr
from xian_py.config import (
    RetryPolicy,
    SubmissionConfig,
    WatcherConfig,
    XianClientConfig,
)
from xian_py.decompiler import ContractDecompiler
from xian_py.exception import TransportError
from xian_py.models import (
    BdsStatus,
    IndexedBlock,
    IndexedEvent,
    NodeStatus,
    PerformanceStatus,
    TransactionReceipt,
    TransactionSubmission,
)
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

    def raise_for_status(self) -> None:
        return None


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

    async def run_send_tx() -> TransactionSubmission:
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
    assert result.submitted is True
    assert result.accepted is True
    assert result.finalized is False
    assert result.tx_hash == "abc123"
    assert result.stamps_estimated == 77
    assert result.stamps_supplied == 87


def test_xian_async_send_tx_reserves_nonces_locally_for_concurrent_calls() -> (
    None
):
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


def test_xian_async_send_tx_invalidates_reserved_nonce_after_checktx_failure() -> (
    None
):
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
                        {
                            "result": {
                                "code": 7,
                                "log": "bad nonce",
                                "hash": "bad",
                            }
                        },
                        {"result": {"code": 0, "hash": "good"}},
                    ]
                ),
            ):
                failed, succeeded = asyncio.run(run_sends())

    assert failed.accepted is False
    assert failed.submitted is True
    assert succeeded.accepted is True
    assert observed_nonces == [7, 7]
    assert get_nonce_async.await_count == 2


def test_xian_async_send_tx_can_wait_for_finalized_receipt() -> None:
    wallet = Wallet()
    client = XianAsync("http://node", chain_id="xian-1", wallet=wallet)

    async def run_send() -> TransactionSubmission:
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

    assert result.accepted is True
    assert result.submitted is True
    assert result.finalized is True
    assert result.receipt is not None
    assert result.receipt.success is True


def test_xian_async_send_tx_async_mode_reports_submission_without_checktx() -> (
    None
):
    wallet = Wallet()
    client = XianAsync("http://node", chain_id="xian-1", wallet=wallet)

    async def run_send() -> TransactionSubmission:
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

    assert result.submitted is True
    assert result.accepted is None
    assert result.finalized is False
    assert result.tx_hash == "abc123"


def test_xian_async_send_tx_commit_mode_does_not_report_finalized_when_checktx_fails() -> (
    None
):
    wallet = Wallet()
    client = XianAsync("http://node", chain_id="xian-1", wallet=wallet)

    async def run_send() -> TransactionSubmission:
        try:
            return await client.send_tx(
                "currency",
                "transfer",
                {"amount": 1, "to": wallet.public_key},
                stamps=100,
                mode="commit",
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
            "broadcast_tx_commit_async",
            AsyncMock(
                return_value={
                    "result": {
                        "hash": "abc123",
                        "height": "0",
                        "check_tx": {
                            "code": 7,
                            "log": "bad nonce",
                        },
                        "tx_result": {
                            "code": 0,
                            "log": "",
                        },
                    }
                }
            ),
        ):
            result = asyncio.run(run_send())

    assert result.submitted is True
    assert result.accepted is False
    assert result.finalized is False
    assert result.message == "bad nonce"


def test_xian_async_get_balance_falls_back_to_abci_query() -> None:
    wallet = Wallet()
    client = XianAsync("http://node", chain_id="xian-1", wallet=wallet)
    client._session = _FakeSession(
        post_responses=[
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

        async def run_get_tx() -> TransactionReceipt:
            try:
                return await client.get_tx("abc123")
            finally:
                await client.close()

        data = asyncio.run(run_get_tx())

    assert data.success is False
    assert data.message == "boom"


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

        async def run_get_tx() -> TransactionReceipt:
            try:
                return await client.get_tx("abc123")
            finally:
                await client.close()

        data = asyncio.run(run_get_tx())

    assert data.success is True
    assert data.transaction == tx
    assert data.execution == execution


def test_xian_async_get_state_decodes_supported_value_shapes() -> None:
    wallet = Wallet()
    client = XianAsync("http://node", chain_id="xian-1", wallet=wallet)
    client._session = _FakeSession(
        post_responses=[
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
        'return decimal("1.25")' in output or "return decimal('1.25')" in output
    )


def test_xian_async_get_contract_clean_uses_decompiler() -> None:
    wallet = Wallet()
    client = XianAsync("http://node", chain_id="xian-1", wallet=wallet)
    client._session = _FakeSession(
        post_responses=[
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


def test_xian_async_exposes_perf_status_as_typed_model() -> None:
    client = XianAsync("http://node", chain_id="xian-1")
    client._session = _FakeSession(
        post_responses=[
            _FakeResponse(
                {
                    "result": {
                        "response": {
                            "value": _b64(
                                '{"enabled":true,"tracer_mode":"native_instruction_v1","node_name":"node-0","chain_id":"xian-local-1","global_metrics":{},"recent_blocks":[]}'
                            ),
                            "info": "dict",
                        }
                    }
                }
            )
        ]
    )

    status = asyncio.run(client.get_perf_status())

    assert isinstance(status, PerformanceStatus)
    assert status.enabled is True
    assert status.tracer_mode == "native_instruction_v1"


def test_xian_async_exposes_bds_status_as_typed_model() -> None:
    client = XianAsync("http://node", chain_id="xian-1")
    client._session = _FakeSession(
        post_responses=[
            _FakeResponse(
                {
                    "result": {
                        "response": {
                            "value": _b64(
                                '{"worker_running":true,"catchup_running":false,"queue_depth":2,"height_lag":1,"indexed":{"indexed_height":41},"spool_pending_count":0,"alerts":[]}'
                            ),
                            "info": "dict",
                        }
                    }
                }
            )
        ]
    )

    status = asyncio.run(client.get_bds_status())

    assert isinstance(status, BdsStatus)
    assert status.worker_running is True
    assert status.indexed_height == 41


def test_sync_client_reuses_background_runtime_until_closed() -> None:
    wallet = Wallet()
    client = Xian("http://node", chain_id="xian-1", wallet=wallet)
    client._async_client.get_balance = AsyncMock(return_value=42)
    client._async_client.close = AsyncMock()

    assert client.get_balance() == 42
    assert client.get_balance() == 42
    client._async_client.close.assert_not_awaited()

    client.close()
    client._async_client.close.assert_awaited_once()


def test_sync_client_context_manager_closes_async_client() -> None:
    wallet = Wallet()
    client = Xian("http://node", chain_id="xian-1", wallet=wallet)
    client._async_client.get_balance = AsyncMock(return_value=42)
    client._async_client.close = AsyncMock()

    with client as managed:
        assert managed.get_balance() == 42

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


def test_xian_async_get_node_status_returns_typed_model() -> None:
    wallet = Wallet()
    client = XianAsync("http://node", wallet=wallet)

    async def run_status() -> NodeStatus:
        try:
            return await client.get_node_status()
        finally:
            await client.close()

    payload = {
        "result": {
            "node_info": {
                "id": "NODE-1",
                "moniker": "validator-1",
                "network": "xian-testnet",
            },
            "sync_info": {
                "latest_block_height": "12",
                "latest_block_hash": "BLOCK-12",
                "latest_app_hash": "APP-12",
                "latest_block_time": "2026-03-23T12:00:00Z",
                "catching_up": False,
            },
        }
    }

    with patch.object(
        tr,
        "request_json_async",
        AsyncMock(return_value=payload),
    ):
        status = asyncio.run(run_status())

    assert status.node_id == "NODE-1"
    assert status.moniker == "validator-1"
    assert status.network == "xian-testnet"
    assert status.latest_block_height == 12
    assert status.latest_block_hash == "BLOCK-12"
    assert status.latest_app_hash == "APP-12"
    assert status.catching_up is False


def test_xian_async_watch_blocks_yields_new_blocks_from_rpc() -> None:
    wallet = Wallet()
    client = XianAsync("http://node", wallet=wallet)

    async def run_watch() -> list[IndexedBlock]:
        try:
            blocks: list[IndexedBlock] = []
            async for block in client.watch_blocks(
                start_height=12,
                poll_interval_seconds=0.01,
            ):
                blocks.append(block)
                if len(blocks) == 2:
                    break
            return blocks
        finally:
            await client.close()

    with patch.object(
        client,
        "get_node_status",
        AsyncMock(
            return_value=NodeStatus(
                node_id="NODE-1",
                moniker="validator-1",
                network="xian-testnet",
                latest_block_height=13,
                latest_block_hash="BLOCK-13",
                latest_app_hash="APP-13",
                latest_block_time_iso="2026-03-23T12:00:13Z",
                catching_up=False,
                raw={},
            )
        ),
    ):
        with patch.object(
            client,
            "_get_live_block",
            AsyncMock(
                side_effect=[
                    IndexedBlock(
                        height=12,
                        block_hash="BLOCK-12",
                        tx_count=1,
                        app_hash="APP-12",
                        block_time_iso="2026-03-23T12:00:12Z",
                        raw={},
                    ),
                    IndexedBlock(
                        height=13,
                        block_hash="BLOCK-13",
                        tx_count=2,
                        app_hash="APP-13",
                        block_time_iso="2026-03-23T12:00:13Z",
                        raw={},
                    ),
                ]
            ),
        ):
            blocks = asyncio.run(run_watch())

    assert [block.height for block in blocks] == [12, 13]
    assert [block.tx_count for block in blocks] == [1, 2]


def test_xian_async_watch_events_uses_after_id_cursor() -> None:
    wallet = Wallet()
    client = XianAsync("http://node", wallet=wallet)

    async def run_watch() -> list[IndexedEvent]:
        try:
            events: list[IndexedEvent] = []
            async for event in client.watch_events(
                "currency",
                "Transfer",
                after_id=10,
                limit=2,
                poll_interval_seconds=0.01,
            ):
                events.append(event)
                if len(events) == 2:
                    break
            return events
        finally:
            await client.close()

    with patch.object(
        client,
        "list_events",
        AsyncMock(
            return_value=[
                IndexedEvent(
                    id=11,
                    tx_hash="TX-11",
                    block_height=12,
                    tx_index=0,
                    event_index=0,
                    contract="currency",
                    event="Transfer",
                    signer="alice",
                    caller="alice",
                    data_indexed={"to": "bob"},
                    data={"amount": "5", "to": "bob"},
                    created="2026-03-23T12:00:12Z",
                    raw={},
                ),
                IndexedEvent(
                    id=12,
                    tx_hash="TX-12",
                    block_height=12,
                    tx_index=1,
                    event_index=0,
                    contract="currency",
                    event="Transfer",
                    signer="alice",
                    caller="alice",
                    data_indexed={"to": "carol"},
                    data={"amount": "7", "to": "carol"},
                    created="2026-03-23T12:00:12Z",
                    raw={},
                ),
            ]
        ),
    ) as list_events:
        events = asyncio.run(run_watch())

    assert [event.id for event in events] == [11, 12]
    first_call = list_events.await_args_list[0]
    assert first_call.kwargs["after_id"] == 10
    assert first_call.kwargs["limit"] == 2


def test_sync_watch_events_wraps_async_iterator() -> None:
    wallet = Wallet()
    client = Xian("http://node", chain_id="xian-testnet", wallet=wallet)

    async def async_events():
        yield IndexedEvent(
            id=21,
            tx_hash="TX-21",
            block_height=21,
            tx_index=0,
            event_index=0,
            contract="currency",
            event="Transfer",
            signer="alice",
            caller="alice",
            data_indexed={"to": "bob"},
            data={"amount": "2", "to": "bob"},
            created="2026-03-23T12:00:21Z",
            raw={},
        )
        yield IndexedEvent(
            id=22,
            tx_hash="TX-22",
            block_height=22,
            tx_index=0,
            event_index=0,
            contract="currency",
            event="Transfer",
            signer="alice",
            caller="alice",
            data_indexed={"to": "carol"},
            data={"amount": "3", "to": "carol"},
            created="2026-03-23T12:00:22Z",
            raw={},
        )

    try:
        with patch.object(
            client._async_client, "watch_events", return_value=async_events()
        ):
            iterator = client.watch_events("currency", "Transfer", after_id=20)
            first = next(iterator)
            second = next(iterator)
            iterator.close()
    finally:
        client.close()

    assert first.id == 21
    assert second.id == 22


def test_xian_async_get_node_status_retries_transport_errors() -> None:
    wallet = Wallet()
    config = XianClientConfig(
        retry=RetryPolicy(
            max_attempts=2,
            initial_delay_seconds=0.0,
            max_delay_seconds=0.0,
        )
    )
    client = XianAsync("http://node", wallet=wallet, config=config)

    async def run_status() -> NodeStatus:
        try:
            return await client.get_node_status()
        finally:
            await client.close()

    payload = {
        "result": {
            "node_info": {
                "id": "NODE-1",
                "moniker": "validator-1",
                "network": "xian-testnet",
            },
            "sync_info": {
                "latest_block_height": "12",
                "latest_block_hash": "BLOCK-12",
                "latest_app_hash": "APP-12",
                "latest_block_time": "2026-03-23T12:00:00Z",
                "catching_up": False,
            },
        }
    }

    with patch.object(
        tr,
        "request_json_async",
        AsyncMock(side_effect=[TransportError("offline"), payload]),
    ) as request_json:
        status = asyncio.run(run_status())

    assert status.latest_block_height == 12
    assert request_json.await_count == 2


def test_xian_async_send_tx_uses_submission_defaults_from_config() -> None:
    wallet = Wallet()
    config = XianClientConfig(
        submission=SubmissionConfig(
            mode="async",
            wait_for_tx=True,
            timeout_seconds=1.0,
            poll_interval_seconds=0.0,
            stamp_margin=0.25,
            min_stamp_headroom=5,
        )
    )
    client = XianAsync(
        "http://node",
        chain_id="xian-1",
        wallet=wallet,
        config=config,
    )

    async def run_send() -> TransactionSubmission:
        try:
            return await client.send_tx(
                "currency",
                "transfer",
                {"amount": 1, "to": wallet.public_key},
            )
        finally:
            await client.close()

    with patch.object(tr, "get_nonce_async", AsyncMock(return_value=11)):
        with patch.object(
            tr,
            "simulate_tx_async",
            AsyncMock(return_value={"stamps_used": 80}),
        ):
            with patch.object(
                tr,
                "create_tx",
                return_value={"signed": True},
            ) as create_tx:
                with patch.object(
                    tr,
                    "broadcast_tx_nowait_async",
                    AsyncMock(return_value={"result": {"hash": "abc123"}}),
                ):
                    with patch.object(
                        tr,
                        "get_tx_async",
                        AsyncMock(
                            return_value={
                                "result": {
                                    "tx": {"payload": {"contract": "currency"}},
                                    "tx_result": {
                                        "code": 0,
                                        "data": {"result": "ok"},
                                    },
                                }
                            }
                        ),
                    ):
                        result = asyncio.run(run_send())

    create_payload = create_tx.call_args.args[0]
    assert create_payload["stamps_supplied"] == 100
    assert result.submitted is True
    assert result.finalized is True
    assert result.receipt is not None


def test_xian_async_watch_events_uses_watcher_defaults_from_config() -> None:
    wallet = Wallet()
    config = XianClientConfig(
        watcher=WatcherConfig(
            poll_interval_seconds=0.01,
            batch_limit=25,
        )
    )
    client = XianAsync("http://node", wallet=wallet, config=config)

    async def run_watch() -> IndexedEvent:
        try:
            async for event in client.watch_events(
                "currency",
                "Transfer",
                after_id=10,
            ):
                return event
        finally:
            await client.close()

    with patch.object(
        client,
        "list_events",
        AsyncMock(
            return_value=[
                IndexedEvent(
                    id=11,
                    tx_hash="TX-11",
                    block_height=12,
                    tx_index=0,
                    event_index=0,
                    contract="currency",
                    event="Transfer",
                    signer="alice",
                    caller="alice",
                    data_indexed={"to": "bob"},
                    data={"amount": "5", "to": "bob"},
                    created="2026-03-23T12:00:12Z",
                    raw={},
                )
            ]
        ),
    ) as list_events:
        event = asyncio.run(run_watch())

    assert event.id == 11
    first_call = list_events.await_args_list[0]
    assert first_call.kwargs["after_id"] == 10
    assert first_call.kwargs["limit"] == 25


def test_async_contract_client_send_merges_kwargs() -> None:
    wallet = Wallet()
    client = XianAsync("http://node", chain_id="xian-1", wallet=wallet)
    contract = client.contract("currency")
    client.send_tx = AsyncMock(
        return_value=TransactionSubmission.from_dict(
            {
                "submitted": True,
                "accepted": True,
                "finalized": False,
                "tx_hash": "abc123",
                "mode": "checktx",
                "nonce": 1,
                "stamps_supplied": 100,
                "stamps_estimated": 90,
                "message": None,
                "response": {},
                "receipt": None,
            }
        )
    )

    result = asyncio.run(
        contract.send(
            "transfer",
            kwargs={"amount": 1},
            to="bob",
            mode="checktx",
        )
    )

    assert result.tx_hash == "abc123"
    client.send_tx.assert_awaited_once_with(
        contract="currency",
        function="transfer",
        kwargs={"amount": 1, "to": "bob"},
        stamps=None,
        nonce=None,
        chain_id=None,
        mode="checktx",
        wait_for_tx=None,
        timeout_seconds=None,
        poll_interval_seconds=None,
        stamp_margin=None,
        min_stamp_headroom=None,
    )


def test_async_token_client_uses_token_helpers() -> None:
    wallet = Wallet()
    client = XianAsync("http://node", chain_id="xian-1", wallet=wallet)
    token = client.token("currency")
    client.get_balance = AsyncMock(return_value=ContractingDecimal("12.5"))
    client.send = AsyncMock(
        return_value=TransactionSubmission.from_dict(
            {
                "submitted": True,
                "accepted": True,
                "finalized": False,
                "tx_hash": "tx-transfer",
                "mode": "checktx",
                "nonce": 1,
                "stamps_supplied": 100,
                "stamps_estimated": 90,
                "message": None,
                "response": {},
                "receipt": None,
            }
        )
    )
    client.get_state = AsyncMock(return_value=ContractingDecimal("7.0"))

    balance = asyncio.run(token.balance_of())
    transfer = asyncio.run(token.transfer("bob", 5, mode="checktx"))
    allowance = asyncio.run(token.allowance("con_dex"))

    assert balance == ContractingDecimal("12.5")
    assert transfer.tx_hash == "tx-transfer"
    assert allowance == ContractingDecimal("7.0")
    client.get_balance.assert_awaited_once_with(
        address=None,
        contract="currency",
    )
    client.send.assert_awaited_once_with(
        amount=5,
        to_address="bob",
        token="currency",
        stamps=None,
        mode="checktx",
        wait_for_tx=None,
        timeout_seconds=None,
        poll_interval_seconds=None,
        stamp_margin=None,
        min_stamp_headroom=None,
    )


def test_async_state_key_client_uses_exact_full_key() -> None:
    wallet = Wallet()
    client = XianAsync("http://node", chain_id="xian-1", wallet=wallet)
    state_key = client.state_key("currency", "balances", "alice")
    client.get_state = AsyncMock(return_value=10)
    client.get_state_history = AsyncMock(return_value=[])

    value = asyncio.run(state_key.get())
    history = asyncio.run(state_key.history(limit=5, offset=2))

    assert value == 10
    assert history == []
    assert state_key.full_key == "currency.balances:alice"
    client.get_state.assert_awaited_once_with("currency", "balances", "alice")
    client.get_state_history.assert_awaited_once_with(
        "currency.balances:alice",
        limit=5,
        offset=2,
    )


def test_sync_contract_and_event_helpers_delegate_to_root_client() -> None:
    wallet = Wallet()
    client = Xian("http://node", chain_id="xian-1", wallet=wallet)
    contract = client.contract("ledger")
    events = client.events("currency", "Transfer")
    state_key = client.state_key("currency", "balances", "alice")
    client.send_tx = lambda **kwargs: kwargs
    client.list_events = lambda contract, event, **kwargs: [
        {"contract": contract, "event": event, **kwargs}
    ]
    client.get_state = lambda contract, variable, *keys: (
        contract,
        variable,
        keys,
    )
    client.get_state_history = lambda key, **kwargs: [{"key": key, **kwargs}]

    try:
        send_payload = contract.send("set_value", value=3)
        event_payload = events.list(after_id=10, limit=5)
        state_value = state_key.get()
        state_history = state_key.history(limit=2)
    finally:
        client.close()

    assert send_payload["contract"] == "ledger"
    assert send_payload["function"] == "set_value"
    assert send_payload["kwargs"] == {"value": 3}
    assert event_payload[0]["after_id"] == 10
    assert event_payload[0]["limit"] == 5
    assert state_value == ("currency", "balances", ("alice",))
    assert state_history[0]["key"] == "currency.balances:alice"
