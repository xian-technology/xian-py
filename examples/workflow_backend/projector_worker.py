from __future__ import annotations

import asyncio
import json
from typing import Any

from xian_py import XianAsync
from xian_py.models import IndexedEvent

try:
    from .common import (
        chain_id,
        node_url,
        optional_wallet,
        projection_path,
        workflow_contract_name,
    )
    from .projection import WorkflowProjection
except ImportError:
    from common import (  # type: ignore
        chain_id,
        node_url,
        optional_wallet,
        projection_path,
        workflow_contract_name,
    )
    from projection import WorkflowProjection  # type: ignore

EVENT_NAMES = (
    "ItemSubmitted",
    "ItemClaimed",
    "ItemCompleted",
    "ItemFailed",
    "ItemCancelled",
)


def _event_sort_key(event: IndexedEvent) -> tuple[int, int, int]:
    if event.id is None:
        raise ValueError("Projection requires event IDs")
    return (
        event.id,
        event.tx_index or 0,
        event.event_index or 0,
    )


async def hydrate_item_snapshot(
    client: XianAsync,
    event: IndexedEvent,
) -> dict[str, Any] | None:
    data = event.data or {}
    item_id = data.get("item_id")
    if item_id is None:
        return None
    return await client.contract(workflow_contract_name()).call(
        "get_item",
        item_id=str(item_id),
    )


async def sync_projection(
    client: XianAsync,
    projection: WorkflowProjection,
    *,
    batch_limit: int | None = None,
    poll_interval_seconds: float | None = None,
) -> None:
    watcher_config = client.config.watcher
    batch_limit = batch_limit or watcher_config.batch_limit
    poll_interval_seconds = (
        poll_interval_seconds or watcher_config.poll_interval_seconds
    )

    if batch_limit <= 0:
        raise ValueError("batch_limit must be > 0")
    if poll_interval_seconds <= 0:
        raise ValueError("poll_interval_seconds must be > 0")

    while True:
        batches = await asyncio.gather(
            *(
                client.list_events(
                    workflow_contract_name(),
                    event_name,
                    limit=batch_limit,
                    after_id=projection.get_cursor(event_name),
                )
                for event_name in EVENT_NAMES
            )
        )
        pending = sorted(
            [event for batch in batches for event in batch],
            key=_event_sort_key,
        )
        if not pending:
            await asyncio.sleep(poll_interval_seconds)
            continue

        hydration_failed = False
        for event in pending:
            try:
                item_snapshot = await hydrate_item_snapshot(client, event)
            except Exception as exc:
                print(
                    json.dumps(
                        {
                            "hydration_error": str(exc),
                            "event": event.event,
                            "id": event.id,
                            "tx_hash": event.tx_hash,
                        },
                        sort_keys=True,
                    )
                )
                hydration_failed = True
                break

            applied = projection.apply_event(event, item_snapshot=item_snapshot)
            print(
                json.dumps(
                    {
                        "applied": applied,
                        "event": event.event,
                        "id": event.id,
                        "tx_hash": event.tx_hash,
                    },
                    sort_keys=True,
                )
            )

        if hydration_failed:
            await asyncio.sleep(poll_interval_seconds)


async def main() -> None:
    projection = WorkflowProjection(
        projection_path(),
        workflow_contract_name(),
    )
    try:
        async with XianAsync(
            node_url(),
            chain_id=chain_id(),
            wallet=optional_wallet(),
        ) as client:
            await sync_projection(client, projection)
    finally:
        projection.close()


if __name__ == "__main__":
    asyncio.run(main())
