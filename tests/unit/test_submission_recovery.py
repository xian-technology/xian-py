import asyncio
import base64
import json
from unittest.mock import AsyncMock, patch

import pytest

from xian_py import NonceReservationError, XianAsync
from xian_py import transaction as tr
from xian_py.config import RetryPolicy, XianClientConfig
from xian_py.exception import RpcError, TransportError


def test_prebroadcast_failure_releases_nonce():
    async def scenario():
        async with XianAsync("http://unused", chain_id="local") as client:
            with (
                patch.object(tr, "get_nonce_async", AsyncMock(return_value=7)),
                patch.object(
                    tr, "broadcast_tx_wait_async", AsyncMock(return_value={"result": {"code": 0}})
                ),
            ):
                with pytest.raises(Exception):
                    await client.send_tx("invalid-name", "transfer", {}, chi=100)
                assert (await client.send_tx("currency", "transfer", {}, chi=100)).nonce == 7

    asyncio.run(scenario())


def test_uncertain_submission_quarantines_nonce_and_exposes_identity():
    async def scenario():
        async with XianAsync(
            "http://unused",
            chain_id="local",
            config=XianClientConfig(retry=RetryPolicy(max_attempts=1)),
        ) as client:
            broadcast = AsyncMock(side_effect=TransportError("lost response"))
            with (
                patch.object(tr, "get_nonce_async", AsyncMock(return_value=7)),
                patch.object(tr, "broadcast_tx_wait_async", broadcast),
            ):
                with pytest.raises(TransportError) as lost:
                    await client.send_tx("currency", "transfer", {"to": "alice"}, chi=100)
                tx_hash = lost.value.details["tx_hash"]
                assert len(tx_hash) == 64
                with pytest.raises(NonceReservationError) as blocked:
                    await client.send_tx("currency", "transfer", {"to": "bob"}, chi=100)
                assert blocked.value.details == {"nonce": 7, "tx_hash": tx_hash}
                with pytest.raises(NonceReservationError):
                    await client.refresh_nonce()
                assert broadcast.await_count == 1

    asyncio.run(scenario())


def test_automatic_broadcasts_wait_for_preceding_admission():
    async def scenario():
        async with XianAsync("http://unused", chain_id="local") as client:
            first_started = asyncio.Event()
            release_first = asyncio.Event()
            seen = []

            async def broadcast(url, prepared, **kwargs):
                nonce = json.loads(prepared.json_bytes)["payload"]["nonce"]
                seen.append(nonce)
                if nonce == 7:
                    first_started.set()
                    await release_first.wait()
                return {"result": {"code": 0}}

            with (
                patch.object(tr, "get_nonce_async", AsyncMock(return_value=7)),
                patch.object(tr, "broadcast_tx_wait_async", broadcast),
            ):
                first = asyncio.create_task(client.send_tx("currency", "transfer", {}, chi=100))
                await first_started.wait()
                second = asyncio.create_task(client.send_tx("currency", "transfer", {}, chi=100))
                await asyncio.sleep(0)
                assert seen == [7]
                release_first.set()
                await asyncio.gather(first, second)
                assert seen == [7, 8]

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "results",
    [
        {"error": {"message": "pruned"}},
        {"result": {"txs_results": []}},
        {"result": {"txs_results": [{}]}},
    ],
)
def test_block_fallback_never_invents_success(results):
    prepared = tr.prepare_transaction({"payload": {"value": 1}})
    block_tx = base64.b64encode(prepared.submitted_bytes).decode()

    async def scenario():
        with (
            patch.object(
                tr,
                "get_block_async",
                AsyncMock(return_value={"result": {"block": {"data": {"txs": [block_tx]}}}}),
            ),
            patch.object(tr, "get_block_results_async", AsyncMock(return_value=results)),
        ):
            with pytest.raises(RpcError):
                await tr._lookup_tx_in_recent_blocks_async(
                    "http://unused", prepared.tx_hash, start_height=1, end_height=1
                )

    asyncio.run(scenario())


def test_cancellation_after_broadcast_quarantines_but_explicit_nonce_does_not_clear_it():
    async def scenario():
        async with XianAsync("http://unused", chain_id="local") as client:
            started = asyncio.Event()

            async def interrupted(*args, **kwargs):
                started.set()
                await asyncio.Event().wait()

            with (
                patch.object(tr, "get_nonce_async", AsyncMock(return_value=7)),
                patch.object(tr, "broadcast_tx_wait_async", interrupted),
            ):
                task = asyncio.create_task(client.send_tx("currency", "transfer", {}, chi=100))
                await started.wait()
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            with (
                patch.object(tr, "get_nonce_async", AsyncMock(return_value=7)),
                patch.object(
                    tr, "broadcast_tx_wait_async", AsyncMock(return_value={"result": {"code": 0}})
                ),
            ):
                explicit = await client.send_tx("currency", "transfer", {}, chi=100, nonce=42)
                assert explicit.nonce == 42
                with pytest.raises(NonceReservationError):
                    await client.send_tx("currency", "transfer", {}, chi=100)

    asyncio.run(scenario())


@pytest.mark.parametrize("code", [0, 1])
@pytest.mark.parametrize(
    "unavailable",
    [
        {"error": {"message": "results not yet available"}},
        {"result": {"txs_results": []}},
        {"result": {"txs_results": [{}]}},
    ],
)
def test_receipt_polling_retries_block_until_actual_execution_results_exist(code, unavailable):
    prepared = tr.prepare_transaction({"payload": {"value": 1}})
    block_tx = base64.b64encode(prepared.submitted_bytes).decode()

    async def scenario():
        blocks = AsyncMock(return_value={"result": {"block": {"data": {"txs": [block_tx]}}}})
        with (
            patch.object(
                tr, "get_tx_async", AsyncMock(return_value={"error": {"message": "index pending"}})
            ),
            patch.object(
                tr,
                "get_status_async",
                AsyncMock(
                    side_effect=[
                        {"result": {"sync_info": {"latest_block_height": "1"}}},
                        {"result": {"sync_info": {"latest_block_height": "2"}}},
                    ]
                ),
            ),
            patch.object(tr, "get_block_async", blocks),
            patch.object(
                tr,
                "get_block_results_async",
                AsyncMock(
                    side_effect=[
                        unavailable,
                        {"result": {"txs_results": [{"code": code, "log": "actual execution"}]}},
                    ]
                ),
            ),
        ):
            result = await tr.wait_for_tx_async(
                "http://unused", prepared.tx_hash, poll_interval_seconds=0
            )
            assert result["result"]["tx_result"]["code"] == code
            assert result["result"]["tx_result"]["log"] == "actual execution"
            assert [call.args[1] for call in blocks.await_args_list] == [1, 1]

    asyncio.run(scenario())
