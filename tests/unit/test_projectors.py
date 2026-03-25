import sqlite3
import unittest
from types import SimpleNamespace

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
    def __init__(self, batches: dict[tuple[str, str], list[IndexedEvent]]) -> None:
        self.batches = batches
        self.calls: list[tuple[str, str, int, int]] = []
        self.config = SimpleNamespace(
            watcher=SimpleNamespace(
                batch_limit=50,
                poll_interval_seconds=0.01,
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


class TestProjectorHelpers(unittest.TestCase):
    def test_merged_event_payload_prefers_unindexed_data_for_duplicates(self) -> None:
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
            applied.append((int(event.id), None if hydrated is None else hydrated["hydrated"]))
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
