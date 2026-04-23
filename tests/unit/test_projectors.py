import asyncio
import json
import sqlite3
import unittest
from types import SimpleNamespace

import aiohttp

from xian_py.models import IndexedEvent
from xian_py.projectors import (
    EventProjector,
    EventProjectorError,
    EventSource,
    SQLiteProjectionState,
    indexed_event_sort_key,
    merged_event_payload,
)


def _event(
    event_id: int | None,
    event_name: str,
    *,
    contract: str = "con_example",
    data: dict | None = None,
    data_indexed: dict | None = None,
) -> IndexedEvent:
    return IndexedEvent(
        id=event_id,
        tx_hash=None if event_id is None else f"tx-{event_id}",
        block_height=1,
        tx_index=0,
        event_index=0,
        contract=contract,
        event=event_name,
        signer=None,
        caller=None,
        data_indexed=data_indexed,
        data=data,
        created="2026-03-25T00:00:00Z",
        raw={"id": event_id, "event": event_name},
    )


class FakeEventClient:
    def __init__(
        self,
        batches: dict[tuple[str, str], list[IndexedEvent]],
        *,
        watcher_mode: str = "poll",
    ) -> None:
        self.batches = batches
        self.calls: list[tuple[str, str, int, int]] = []
        self.config = SimpleNamespace(
            watcher=SimpleNamespace(
                batch_limit=50,
                poll_interval_seconds=0.01,
                mode=watcher_mode,
                websocket_heartbeat_seconds=25.0,
            )
        )

    async def list_events(
        self,
        contract: str,
        event: str,
        *,
        limit: int,
        after_id: int,
    ) -> list[IndexedEvent]:
        self.calls.append((contract, event, limit, after_id))
        return list(self.batches.get((contract, event), []))


class _FakeWebSocket:
    def __init__(self, payloads: list[dict]):
        self.payloads = list(payloads)
        self.sent: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)

    async def receive(self):
        if not self.payloads:
            return SimpleNamespace(type=aiohttp.WSMsgType.CLOSED, data=None)
        return SimpleNamespace(
            type=aiohttp.WSMsgType.TEXT,
            data=json.dumps(self.payloads.pop(0)),
        )

    def exception(self):
        return None


class _FakeWebSocketSession:
    def __init__(
        self, *, websocket=None, connect_error: Exception | None = None
    ):
        self.websocket = websocket
        self.connect_error = connect_error
        self.ws_connect_calls: list[tuple[str, dict]] = []

    def ws_connect(self, url: str, **kwargs):
        self.ws_connect_calls.append((url, kwargs))
        if self.connect_error is not None:
            raise self.connect_error
        return self.websocket


class LiveWakeupClient(FakeEventClient):
    def __init__(
        self,
        *,
        responses: list[list[IndexedEvent]],
        websocket: _FakeWebSocket,
        event_sources: list[EventSource],
    ) -> None:
        super().__init__({}, watcher_mode="auto")
        self._responses = list(responses)
        self.session = _FakeWebSocketSession(websocket=websocket)
        self._event_sources = event_sources

    async def list_events(
        self,
        contract: str,
        event: str,
        *,
        limit: int,
        after_id: int,
    ) -> list[IndexedEvent]:
        self.calls.append((contract, event, limit, after_id))
        if self._responses:
            return list(self._responses.pop(0))
        return []

    def _resolve_cometbft_ws_url(self) -> str:
        return "ws://rpc.example:26657/websocket"


class TestProjectorHelpers(unittest.TestCase):
    def test_merged_event_payload_prefers_unindexed_data_for_duplicates(
        self,
    ) -> None:
        event = _event(
            1,
            "Transfer",
            data={"amount": "10", "from": "alice"},
            data_indexed={"from": "indexed-alice", "to": "bob"},
        )

        assert merged_event_payload(event) == {
            "from": "alice",
            "to": "bob",
            "amount": "10",
        }

    def test_indexed_event_sort_key_requires_ids(self) -> None:
        with self.assertRaises(ValueError):
            indexed_event_sort_key(_event(None, "Transfer"))

    def test_sqlite_projection_state_round_trips_cursors(self) -> None:
        connection = sqlite3.connect(":memory:")
        try:
            connection.row_factory = sqlite3.Row
            state = SQLiteProjectionState(connection)

            with connection:
                state.init_schema()
                state.set_int("cursor:Issue", 10)
                state.set_int("cursor:Transfer", 12)

            assert state.get_int("cursor:Issue") == 10
            assert state.get_int("cursor:Missing") == 0
            assert state.list_ints(
                prefix="cursor:",
                strip_prefix="cursor:",
            ) == {"Issue": 10, "Transfer": 12}
        finally:
            connection.close()


class TestEventProjector(unittest.IsolatedAsyncioTestCase):
    async def test_sync_once_orders_events_and_passes_hydration(self) -> None:
        client = FakeEventClient(
            {
                ("con_a", "One"): [_event(2, "One", contract="con_a")],
                ("con_b", "Two"): [_event(1, "Two", contract="con_b")],
                ("con_a", "Three"): [_event(3, "Three", contract="con_a")],
            }
        )
        cursors = {
            "con_a:One": 5,
            "con_b:Two": 7,
            "con_a:Three": 9,
        }
        applied: list[tuple[int, str | None]] = []
        callback_order: list[int] = []

        async def hydrate(event: IndexedEvent) -> dict[str, str]:
            return {"hydrated": str(event.event)}

        async def apply_event(
            event: IndexedEvent,
            hydrated: dict[str, str] | None,
        ) -> bool:
            applied.append(
                (
                    int(event.id),
                    None if hydrated is None else hydrated["hydrated"],
                )
            )
            return True

        async def on_applied(event: IndexedEvent, applied_ok: bool) -> None:
            if applied_ok:
                callback_order.append(int(event.id))

        projector = EventProjector[dict[str, str]](
            client=client,
            event_sources=[
                EventSource("con_a", "One"),
                EventSource("con_b", "Two"),
                EventSource("con_a", "Three"),
            ],
            get_cursor=lambda source: cursors[source.key],
            hydrate_event=hydrate,
            apply_event=apply_event,
        )

        processed = await projector.sync_once(on_applied=on_applied)

        assert processed == 3
        assert applied == [(1, "Two"), (2, "One"), (3, "Three")]
        assert callback_order == [1, 2, 3]
        assert client.calls == [
            ("con_a", "One", 50, 5),
            ("con_b", "Two", 50, 7),
            ("con_a", "Three", 50, 9),
        ]

    async def test_sync_once_wraps_hydration_failures(self) -> None:
        failing_event = _event(4, "Failing", contract="con_a")
        client = FakeEventClient({("con_a", "Failing"): [failing_event]})

        async def hydrate(_event: IndexedEvent) -> None:
            raise RuntimeError("boom")

        projector = EventProjector[None](
            client=client,
            event_sources=[EventSource("con_a", "Failing")],
            get_cursor=lambda _source: 0,
            hydrate_event=hydrate,
            apply_event=lambda _event, _hydrated: True,
        )

        with self.assertRaises(EventProjectorError) as ctx:
            await projector.sync_once()

        assert ctx.exception.phase == "hydrate"
        assert ctx.exception.event == failing_event
        assert isinstance(ctx.exception.cause, RuntimeError)

    async def test_run_forever_uses_websocket_wakeups_before_next_poll(
        self,
    ) -> None:
        transfer = _event(1, "Transfer", contract="currency")
        websocket = _FakeWebSocket(
            [
                {"jsonrpc": "2.0", "id": "xian-py-projector-0", "result": {}},
                {"jsonrpc": "2.0", "result": {"query": "tm.event='Tx'"}},
            ]
        )
        event_sources = [EventSource("currency", "Transfer")]
        client = LiveWakeupClient(
            responses=[[], [transfer], []],
            websocket=websocket,
            event_sources=event_sources,
        )
        cursors = {event_sources[0].key: 0}
        applied_ids: list[int] = []
        applied_event = asyncio.Event()

        async def apply_event(
            event: IndexedEvent,
            _hydrated: None,
        ) -> bool:
            cursors[event_sources[0].key] = int(event.id)
            applied_ids.append(int(event.id))
            applied_event.set()
            return True

        projector = EventProjector[None](
            client=client,
            event_sources=event_sources,
            get_cursor=lambda source: cursors[source.key],
            apply_event=apply_event,
        )

        task = asyncio.create_task(projector.run_forever())
        try:
            await asyncio.wait_for(applied_event.wait(), timeout=0.2)
        finally:
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        assert applied_ids == [1]
        assert client.session.ws_connect_calls[0][0] == (
            "ws://rpc.example:26657/websocket"
        )
        assert websocket.sent == [
            {
                "jsonrpc": "2.0",
                "method": "subscribe",
                "id": "xian-py-projector-0",
                "params": {
                    "query": "tm.event='Tx' AND Transfer.contract='currency'"
                },
            }
        ]

    async def test_run_forever_retries_until_live_wakeup_is_indexed(
        self,
    ) -> None:
        transfer = _event(1, "Transfer", contract="currency")
        websocket = _FakeWebSocket(
            [
                {"jsonrpc": "2.0", "id": "xian-py-projector-0", "result": {}},
                {"jsonrpc": "2.0", "result": {"query": "tm.event='Tx'"}},
            ]
        )
        event_sources = [EventSource("currency", "Transfer")]
        client = LiveWakeupClient(
            responses=[[], [], [transfer], []],
            websocket=websocket,
            event_sources=event_sources,
        )
        cursors = {event_sources[0].key: 0}
        applied_ids: list[int] = []
        applied_event = asyncio.Event()

        async def apply_event(
            event: IndexedEvent,
            _hydrated: None,
        ) -> bool:
            cursors[event_sources[0].key] = int(event.id)
            applied_ids.append(int(event.id))
            applied_event.set()
            return True

        projector = EventProjector[None](
            client=client,
            event_sources=event_sources,
            get_cursor=lambda source: cursors[source.key],
            apply_event=apply_event,
            poll_interval_seconds=30.0,
        )

        task = asyncio.create_task(projector.run_forever())
        try:
            await asyncio.wait_for(applied_event.wait(), timeout=1.5)
        finally:
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        assert applied_ids == [1]
        assert client.calls[:3] == [
            ("currency", "Transfer", 50, 0),
            ("currency", "Transfer", 50, 0),
            ("currency", "Transfer", 50, 0),
        ]
        assert client.calls[3:] in (
            [],
            [("currency", "Transfer", 50, 1)],
        )

    async def test_run_forever_deduplicates_live_wakeup_subscriptions(
        self,
    ) -> None:
        websocket = _FakeWebSocket(
            [{"jsonrpc": "2.0", "id": "xian-py-projector-0", "result": {}}]
        )
        event_sources = [
            EventSource("currency", "Transfer"),
            EventSource(
                "currency",
                "Transfer",
                cursor_key="currency:Transfer:secondary",
            ),
        ]
        client = LiveWakeupClient(
            responses=[[], []],
            websocket=websocket,
            event_sources=event_sources,
        )
        wakeup_started = asyncio.Event()
        original_ws_connect = client.session.ws_connect

        def tracking_ws_connect(url: str, **kwargs):
            wakeup_started.set()
            return original_ws_connect(url, **kwargs)

        client.session.ws_connect = tracking_ws_connect

        projector = EventProjector[None](
            client=client,
            event_sources=event_sources,
            get_cursor=lambda _source: 0,
            apply_event=lambda _event, _hydrated: True,
        )

        task = asyncio.create_task(projector.run_forever())
        try:
            await asyncio.wait_for(wakeup_started.wait(), timeout=0.2)
            await asyncio.sleep(0)
        finally:
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        assert websocket.sent == [
            {
                "jsonrpc": "2.0",
                "method": "subscribe",
                "id": "xian-py-projector-0",
                "params": {
                    "query": "tm.event='Tx' AND Transfer.contract='currency'"
                },
            }
        ]
