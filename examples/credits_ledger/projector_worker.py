from __future__ import annotations

import asyncio
import json

from xian_py import EventProjector, EventProjectorError, EventSource, XianAsync

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


async def sync_projection(
    client: XianAsync,
    projection: CreditsLedgerProjection,
    *,
    batch_limit: int | None = None,
    poll_interval_seconds: float | None = None,
) -> None:
    projector = EventProjector[None](
        client=client,
        event_sources=[
            EventSource(
                contract_name(),
                event_name,
                cursor_key=event_name,
            )
            for event_name in EVENT_NAMES
        ],
        get_cursor=lambda event_source: projection.get_cursor(event_source.key),
        apply_event=lambda event, _hydrated: projection.apply_event(event),
        batch_limit=batch_limit,
        poll_interval_seconds=poll_interval_seconds,
    )

    async def on_applied(event, applied: bool) -> None:
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
