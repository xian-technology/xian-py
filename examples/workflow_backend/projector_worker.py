from __future__ import annotations

import asyncio
import json
from typing import Any

from xian_py import (
    EventProjector,
    EventProjectorError,
    EventSource,
    XianAsync,
    merged_event_payload,
)

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


async def hydrate_item_snapshot(
    client: XianAsync,
    event,
) -> dict[str, Any] | None:
    data = merged_event_payload(event)
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
    projector = EventProjector[dict[str, Any] | None](
        client=client,
        event_sources=[
            EventSource(
                workflow_contract_name(),
                event_name,
                cursor_key=event_name,
            )
            for event_name in EVENT_NAMES
        ],
        get_cursor=lambda event_source: projection.get_cursor(event_source.key),
        hydrate_event=lambda event: hydrate_item_snapshot(client, event),
        apply_event=lambda event, item_snapshot: projection.apply_event(
            event,
            item_snapshot=item_snapshot,
        ),
        batch_limit=batch_limit,
        poll_interval_seconds=poll_interval_seconds,
    )

    async def on_applied(event, applied: bool) -> None:
        data = merged_event_payload(event)
        print(
            json.dumps(
                {
                    "applied": applied,
                    "event": event.event,
                    "id": event.id,
                    "tx_hash": event.tx_hash,
                    "data": data,
                },
                sort_keys=True,
            )
        )

    async def on_error(exc: EventProjectorError) -> None:
        print(
            json.dumps(
                {
                    "error": str(exc.cause),
                    "phase": exc.phase,
                    "event": exc.event.event,
                    "id": exc.event.id,
                    "tx_hash": exc.event.tx_hash,
                },
                sort_keys=True,
            )
        )

    await projector.run_forever(
        on_applied=on_applied,
        on_error=on_error,
    )


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
