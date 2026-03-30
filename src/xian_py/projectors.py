from __future__ import annotations

import asyncio
import inspect
import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Generic, Sequence, TypeVar

import aiohttp

from xian_py.exception import TransportError, XianException
from xian_py.models import IndexedEvent

HydrationT = TypeVar("HydrationT")


@dataclass(frozen=True)
class EventSource:
    contract: str
    event: str
    cursor_key: str | None = None

    @property
    def key(self) -> str:
        if self.cursor_key is not None:
            return self.cursor_key
        if self.contract:
            return f"{self.contract}:{self.event}"
        return self.event


def merged_event_payload(event: IndexedEvent) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if event.data_indexed:
        payload.update(event.data_indexed)
    if event.data:
        payload.update(event.data)
    return payload


def indexed_event_sort_key(event: IndexedEvent) -> tuple[int, int, int]:
    if event.id is None:
        raise ValueError("Projection requires event IDs")
    return (
        event.id,
        event.tx_index or 0,
        event.event_index or 0,
    )


class SQLiteProjectionState:
    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        table_name: str = "projection_state",
    ) -> None:
        self.connection = connection
        self.table_name = table_name

    def init_schema(self) -> None:
        self.connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {self.table_name} (
                name TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )

    def get_int(self, name: str, *, default: int = 0) -> int:
        row = self.connection.execute(
            f"SELECT value FROM {self.table_name} WHERE name = ?",
            (name,),
        ).fetchone()
        return int(row["value"]) if row is not None else default

    def list_ints(
        self,
        *,
        prefix: str | None = None,
        strip_prefix: str | None = None,
    ) -> dict[str, int]:
        if prefix is None:
            rows = self.connection.execute(
                f"SELECT name, value FROM {self.table_name}"
            ).fetchall()
        else:
            rows = self.connection.execute(
                f"SELECT name, value FROM {self.table_name} WHERE name LIKE ?",
                (f"{prefix}%",),
            ).fetchall()
        values: dict[str, int] = {}
        for row in rows:
            name = str(row["name"])
            if strip_prefix is not None and name.startswith(strip_prefix):
                name = name[len(strip_prefix) :]
            values[name] = int(row["value"])
        return values

    def set_int(self, name: str, value: int) -> None:
        self.connection.execute(
            f"""
            INSERT INTO {self.table_name} (name, value)
            VALUES (?, ?)
            ON CONFLICT(name) DO UPDATE SET value = excluded.value
            """,
            (name, str(value)),
        )


class EventProjectorError(RuntimeError):
    def __init__(
        self,
        *,
        phase: str,
        event: IndexedEvent,
        cause: Exception,
    ) -> None:
        self.phase = phase
        self.event = event
        self.cause = cause
        super().__init__(
            f"{phase} failed for event {event.event!r} "
            f"(id={event.id}, tx_hash={event.tx_hash}): {cause}"
        )


AppliedCallback = Callable[
    [IndexedEvent, bool],
    Any | Awaitable[Any],
]
ErrorCallback = Callable[
    [EventProjectorError],
    Any | Awaitable[Any],
]


def _quote_cometbft_query_value(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"


def _build_cometbft_event_query(contract: str, event: str) -> str:
    return (
        "tm.event='Tx' "
        f"AND {event}.contract={_quote_cometbft_query_value(contract)}"
    )


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


class EventProjector(Generic[HydrationT]):
    def __init__(
        self,
        *,
        client: Any,
        event_sources: Sequence[EventSource],
        get_cursor: Callable[[EventSource], int],
        apply_event: Callable[
            [IndexedEvent, HydrationT | None],
            bool | Awaitable[bool],
        ],
        hydrate_event: Callable[
            [IndexedEvent],
            HydrationT | None | Awaitable[HydrationT | None],
        ]
        | None = None,
        batch_limit: int | None = None,
        poll_interval_seconds: float | None = None,
    ) -> None:
        watcher_config = getattr(client.config, "watcher", None)
        resolved_batch_limit = (
            batch_limit
            if batch_limit is not None
            else getattr(watcher_config, "batch_limit", None)
        )
        resolved_poll_interval = (
            poll_interval_seconds
            if poll_interval_seconds is not None
            else getattr(watcher_config, "poll_interval_seconds", None)
        )

        if resolved_batch_limit is None or resolved_batch_limit <= 0:
            raise ValueError("batch_limit must be > 0")
        if resolved_poll_interval is None or resolved_poll_interval <= 0:
            raise ValueError("poll_interval_seconds must be > 0")

        self.client = client
        self.event_sources = list(event_sources)
        self.get_cursor = get_cursor
        self.apply_event = apply_event
        self.hydrate_event = hydrate_event
        self.batch_limit = resolved_batch_limit
        self.poll_interval_seconds = resolved_poll_interval

    def _watcher_mode(self) -> str:
        watcher_config = getattr(self.client.config, "watcher", None)
        return str(getattr(watcher_config, "mode", "poll"))

    def _websocket_heartbeat_seconds(self) -> float:
        watcher_config = getattr(self.client.config, "watcher", None)
        heartbeat = getattr(watcher_config, "websocket_heartbeat_seconds", 25.0)
        return float(heartbeat) if heartbeat is not None else 25.0

    def _live_wakeup_specs(self) -> list[tuple[str, str]]:
        seen: set[tuple[str, str]] = set()
        specs: list[tuple[str, str]] = []
        for event_source in self.event_sources:
            spec = (event_source.contract, event_source.event)
            if spec in seen:
                continue
            seen.add(spec)
            specs.append(spec)
        return specs

    @staticmethod
    def _signal_live_wakeup(queue: asyncio.Queue[None]) -> None:
        try:
            queue.put_nowait(None)
        except asyncio.QueueFull:
            pass

    @staticmethod
    async def _receive_ws_json(
        ws: aiohttp.ClientWebSocketResponse,
    ) -> dict[str, Any]:
        while True:
            msg = await ws.receive()
            if msg.type == aiohttp.WSMsgType.TEXT:
                try:
                    payload = json.loads(msg.data)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    return payload
                continue
            if msg.type == aiohttp.WSMsgType.ERROR:
                raise TransportError(
                    "CometBFT websocket error",
                    cause=ws.exception(),
                )
            if msg.type in (
                aiohttp.WSMsgType.CLOSE,
                aiohttp.WSMsgType.CLOSING,
                aiohttp.WSMsgType.CLOSED,
            ):
                raise TransportError("CometBFT websocket closed")

    async def _subscribe_live_wakeup_sources(
        self,
        ws: aiohttp.ClientWebSocketResponse,
        *,
        queue: asyncio.Queue[None],
    ) -> None:
        for index, (contract, event) in enumerate(self._live_wakeup_specs()):
            subscription_id = f"xian-py-projector-{index}"
            await ws.send_json(
                {
                    "jsonrpc": "2.0",
                    "method": "subscribe",
                    "id": subscription_id,
                    "params": {
                        "query": _build_cometbft_event_query(contract, event)
                    },
                }
            )

            while True:
                payload = await self._receive_ws_json(ws)
                if "error" in payload:
                    raise XianException(
                        payload.get("error", {}).get("message")
                        or "CometBFT subscription failed",
                        details=payload,
                    )
                if payload.get("id") == subscription_id:
                    break
                self._signal_live_wakeup(queue)

    async def _run_live_wakeup_worker(
        self,
        *,
        queue: asyncio.Queue[None],
    ) -> None:
        if self._watcher_mode() == "poll":
            return

        resolve_ws_url = getattr(self.client, "_resolve_cometbft_ws_url", None)
        if not callable(resolve_ws_url):
            return

        specs = self._live_wakeup_specs()
        if not specs:
            return

        session = getattr(self.client, "session", None)
        if session is None or not hasattr(session, "ws_connect"):
            return

        while True:
            try:
                async with session.ws_connect(
                    resolve_ws_url(),
                    heartbeat=self._websocket_heartbeat_seconds(),
                    receive_timeout=None,
                ) as ws:
                    await self._subscribe_live_wakeup_sources(
                        ws,
                        queue=queue,
                    )
                    while True:
                        payload = await self._receive_ws_json(ws)
                        if "error" in payload:
                            raise XianException(
                                payload.get("error", {}).get("message")
                                or "CometBFT subscription failed",
                                details=payload,
                            )
                        self._signal_live_wakeup(queue)
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(self.poll_interval_seconds)

    async def _wait_for_cycle_wakeup(
        self,
        queue: asyncio.Queue[None] | None,
    ) -> bool:
        if queue is None:
            await asyncio.sleep(self.poll_interval_seconds)
            return False

        try:
            await asyncio.wait_for(
                queue.get(),
                timeout=self.poll_interval_seconds,
            )
            return True
        except asyncio.TimeoutError:
            return False

    async def _sync_after_live_wakeup(
        self,
        *,
        on_applied: AppliedCallback | None = None,
        on_error: ErrorCallback | None = None,
    ) -> int:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.poll_interval_seconds

        while True:
            try:
                processed = await self.sync_once(on_applied=on_applied)
            except EventProjectorError as exc:
                if on_error is None:
                    raise
                await _maybe_await(on_error(exc))
                processed = 0

            if processed > 0:
                return processed

            remaining_seconds = deadline - loop.time()
            if remaining_seconds <= 0:
                return 0

            await asyncio.sleep(min(1.0, remaining_seconds))

    async def fetch_pending_events(self) -> list[IndexedEvent]:
        batches = await asyncio.gather(
            *(
                self.client.list_events(
                    event_source.contract,
                    event_source.event,
                    limit=self.batch_limit,
                    after_id=self.get_cursor(event_source),
                )
                for event_source in self.event_sources
            )
        )
        pending = [event for batch in batches for event in batch]
        return sorted(pending, key=indexed_event_sort_key)

    async def sync_once(
        self,
        *,
        on_applied: AppliedCallback | None = None,
    ) -> int:
        pending = await self.fetch_pending_events()
        for event in pending:
            hydrated: HydrationT | None = None
            if self.hydrate_event is not None:
                try:
                    hydrated = await _maybe_await(self.hydrate_event(event))
                except Exception as exc:
                    raise EventProjectorError(
                        phase="hydrate",
                        event=event,
                        cause=exc,
                    ) from exc
            try:
                applied = bool(
                    await _maybe_await(self.apply_event(event, hydrated))
                )
            except Exception as exc:
                raise EventProjectorError(
                    phase="apply",
                    event=event,
                    cause=exc,
                ) from exc

            if on_applied is not None:
                await _maybe_await(on_applied(event, applied))
        return len(pending)

    async def run_forever(
        self,
        *,
        on_applied: AppliedCallback | None = None,
        on_error: ErrorCallback | None = None,
    ) -> None:
        wakeup_queue: asyncio.Queue[None] | None = None
        wakeup_worker: asyncio.Task[None] | None = None

        if self._watcher_mode() != "poll":
            wakeup_queue = asyncio.Queue(maxsize=1)
            wakeup_worker = asyncio.create_task(
                self._run_live_wakeup_worker(queue=wakeup_queue)
            )

        try:
            while True:
                try:
                    processed = await self.sync_once(on_applied=on_applied)
                except EventProjectorError as exc:
                    if on_error is None:
                        raise
                    await _maybe_await(on_error(exc))
                    woke_from_live_tail = await self._wait_for_cycle_wakeup(
                        wakeup_queue
                    )
                    if woke_from_live_tail:
                        await self._sync_after_live_wakeup(
                            on_applied=on_applied,
                            on_error=on_error,
                        )
                    continue

                if processed == 0:
                    woke_from_live_tail = await self._wait_for_cycle_wakeup(
                        wakeup_queue
                    )
                    if woke_from_live_tail:
                        await self._sync_after_live_wakeup(
                            on_applied=on_applied,
                            on_error=on_error,
                        )
        finally:
            if wakeup_worker is not None:
                wakeup_worker.cancel()
                await asyncio.gather(wakeup_worker, return_exceptions=True)
