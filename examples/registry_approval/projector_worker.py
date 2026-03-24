from __future__ import annotations

import asyncio
import json

from xian_py import XianAsync
from xian_py.models import IndexedEvent

try:
    from .common import (
        approval_contract_name,
        chain_id,
        node_url,
        optional_wallet,
        projection_path,
        registry_contract_name,
    )
    from .projection import RegistryApprovalProjection
except ImportError:
    from common import (  # type: ignore
        approval_contract_name,
        chain_id,
        node_url,
        optional_wallet,
        projection_path,
        registry_contract_name,
    )
    from projection import RegistryApprovalProjection  # type: ignore

EVENT_SOURCES = (
    (approval_contract_name, "ProposalSubmitted"),
    (approval_contract_name, "ProposalApproved"),
    (approval_contract_name, "ProposalExecuted"),
    (registry_contract_name, "RecordUpserted"),
    (registry_contract_name, "RecordRevoked"),
)
PROPOSAL_EVENTS = {
    "ProposalSubmitted",
    "ProposalApproved",
    "ProposalExecuted",
}
RECORD_EVENTS = {
    "RecordUpserted",
    "RecordRevoked",
}


def _event_sort_key(event: IndexedEvent) -> tuple[int, int, int]:
    if event.id is None:
        raise ValueError("Projection requires event IDs")
    return (
        event.id,
        event.tx_index or 0,
        event.event_index or 0,
    )


async def hydrate_projection_state(
    client: XianAsync,
    event: IndexedEvent,
) -> tuple[dict | None, dict | None]:
    proposal_snapshot = None
    record_snapshot = None
    data = event.data or {}

    if event.event in PROPOSAL_EVENTS and data.get("proposal_id") is not None:
        proposal_snapshot = await client.contract(
            approval_contract_name()
        ).simulate(
            "get_proposal",
            proposal_id=int(data["proposal_id"]),
        )

    if event.event in RECORD_EVENTS and data.get("record_id") is not None:
        record_snapshot = await client.contract(
            registry_contract_name()
        ).simulate(
            "get_record",
            record_id=str(data["record_id"]),
        )

    return proposal_snapshot, record_snapshot


async def sync_projection(
    client: XianAsync,
    projection: RegistryApprovalProjection,
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
                    contract_name_factory(),
                    event_name,
                    limit=batch_limit,
                    after_id=projection.get_cursor(
                        contract_name_factory(),
                        event_name,
                    ),
                )
                for contract_name_factory, event_name in EVENT_SOURCES
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
                proposal_snapshot, record_snapshot = (
                    await hydrate_projection_state(client, event)
                )
            except Exception as exc:
                print(
                    json.dumps(
                        {
                            "hydration_error": str(exc),
                            "contract": event.contract,
                            "event": event.event,
                            "id": event.id,
                            "tx_hash": event.tx_hash,
                        },
                        sort_keys=True,
                    )
                )
                hydration_failed = True
                break

            applied = projection.apply_event(
                event,
                proposal_snapshot=proposal_snapshot,
                record_snapshot=record_snapshot,
            )
            print(
                json.dumps(
                    {
                        "applied": applied,
                        "contract": event.contract,
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
    projection = RegistryApprovalProjection(
        projection_path(),
        registry_contract=registry_contract_name(),
        approval_contract=approval_contract_name(),
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
