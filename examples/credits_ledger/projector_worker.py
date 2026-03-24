from __future__ import annotations

import asyncio
import json

from xian_py import XianAsync
from xian_py.models import IndexedEvent

try:
    from .common import (
        chain_id,
        contract_name,
        node_url,
        optional_wallet,
        projection_path,
    )
    from .projection import CreditsLedgerProjection
except ImportError:
    from common import (  # type: ignore
        chain_id,
        contract_name,
        node_url,
        optional_wallet,
        projection_path,
    )
    from projection import CreditsLedgerProjection  # type: ignore

EVENT_NAMES = ("Issue", "Transfer", "Burn")


def _event_sort_key(event: IndexedEvent) -> tuple[int, int, int]:
    if event.id is None:
        raise ValueError("Projection requires event IDs")
    return (
        event.id,
        event.tx_index or 0,
        event.event_index or 0,
    )


async def sync_projection(
    client: XianAsync,
    projection: CreditsLedgerProjection,
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
                    contract_name(),
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

        for event in pending:
            applied = projection.apply_event(event)
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


async def main() -> None:
    projection = CreditsLedgerProjection(projection_path(), contract_name())
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
