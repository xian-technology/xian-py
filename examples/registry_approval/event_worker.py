# ruff: noqa: I001

from __future__ import annotations

import asyncio
import json

from xian_py import XianAsync

try:
    from .common import (
        approval_contract_name,
        chain_id,
        cursor_path,
        node_url,
        optional_wallet,
        registry_contract_name,
    )
except ImportError:
    from common import (  # type: ignore
        approval_contract_name,
        chain_id,
        cursor_path,
        node_url,
        optional_wallet,
        registry_contract_name,
    )

EVENT_SOURCES = (
    (approval_contract_name, "ProposalSubmitted"),
    (approval_contract_name, "ProposalApproved"),
    (approval_contract_name, "ProposalExecuted"),
    (registry_contract_name, "RecordUpserted"),
    (registry_contract_name, "RecordRevoked"),
)


def load_cursors() -> dict[str, int]:
    path = cursor_path()
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_cursors(cursors: dict[str, int]) -> None:
    cursor_path().write_text(
        json.dumps(cursors, indent=2, sort_keys=True),
        encoding="utf-8",
    )


async def watch_event(
    client: XianAsync,
    contract_name_factory,
    event_name: str,
    cursors: dict[str, int],
) -> None:
    contract_name = contract_name_factory()
    cursor_key = f"{contract_name}:{event_name}"
    event_client = client.contract(contract_name).events(event_name)
    async for event in event_client.watch(after_id=cursors.get(cursor_key)):
        print(
            json.dumps(
                {
                    "contract": contract_name,
                    "event": event_name,
                    "id": event.id,
                    "tx_hash": event.tx_hash,
                    "data": event.data,
                },
                sort_keys=True,
            )
        )
        if event.id is not None:
            cursors[cursor_key] = event.id
            save_cursors(cursors)


async def main() -> None:
    cursors = load_cursors()
    async with XianAsync(
        node_url(),
        chain_id=chain_id(),
        wallet=optional_wallet(),
    ) as client:
        await asyncio.gather(
            *(
                watch_event(client, contract_name_factory, event_name, cursors)
                for contract_name_factory, event_name in EVENT_SOURCES
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
