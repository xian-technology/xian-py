from __future__ import annotations

import asyncio
import json

from xian_py import (
    EventProjector,
    EventProjectorError,
    EventSource,
    XianAsync,
    merged_event_payload,
)

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


async def hydrate_projection_state(
    client: XianAsync,
    event,
) -> tuple[dict | None, dict | None]:
    proposal_snapshot = None
    record_snapshot = None
    data = merged_event_payload(event)

    if event.event in PROPOSAL_EVENTS and data.get("proposal_id") is not None:
        proposal_snapshot = await client.contract(
            approval_contract_name()
        ).call(
            "get_proposal",
            proposal_id=int(data["proposal_id"]),
        )

    if event.event in RECORD_EVENTS and data.get("record_id") is not None:
        record_snapshot = await client.contract(
            registry_contract_name()
        ).call(
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
    projector = EventProjector[tuple[dict | None, dict | None]](
        client=client,
        event_sources=[
            EventSource(
                contract_name_factory(),
                event_name,
                cursor_key=f"{contract_name_factory()}:{event_name}",
            )
            for contract_name_factory, event_name in EVENT_SOURCES
        ],
        get_cursor=lambda event_source: projection.get_cursor(
            event_source.contract,
            event_source.event,
        ),
        hydrate_event=lambda event: hydrate_projection_state(client, event),
        apply_event=lambda event, hydrated: projection.apply_event(
            event,
            proposal_snapshot=(
                hydrated[0] if hydrated is not None else None
            ),
            record_snapshot=(
                hydrated[1] if hydrated is not None else None
            ),
        ),
        batch_limit=batch_limit,
        poll_interval_seconds=poll_interval_seconds,
    )

    async def on_applied(event, applied: bool) -> None:
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

    async def on_error(exc: EventProjectorError) -> None:
        print(
            json.dumps(
                {
                    "error": str(exc.cause),
                    "phase": exc.phase,
                    "contract": exc.event.contract,
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
