from __future__ import annotations

import asyncio
import json

from xian_py import XianAsync

try:
    from .common import (
        chain_id,
        contract_name,
        cursor_path,
        node_url,
        optional_wallet,
    )
except ImportError:
    from common import (  # type: ignore
        chain_id,
        contract_name,
        cursor_path,
        node_url,
        optional_wallet,
    )

EVENT_NAMES = ("Issue", "Transfer", "Burn")


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
    event_name: str,
    cursors: dict[str, int],
) -> None:
    event_client = client.contract(contract_name()).events(event_name)
    async for event in event_client.watch(after_id=cursors.get(event_name)):
        print(
            json.dumps(
                {
                    "event": event_name,
                    "id": event.id,
                    "tx_hash": event.tx_hash,
                    "data": event.data,
                },
                sort_keys=True,
            )
        )
        if event.id is not None:
            cursors[event_name] = event.id
            save_cursors(cursors)


async def main() -> None:
    cursors = load_cursors()
    async with XianAsync(
        node_url(),
        chain_id=chain_id(),
        wallet=optional_wallet(),
    ) as client:
        await asyncio.gather(
            *(watch_event(client, event_name, cursors) for event_name in EVENT_NAMES)
        )


if __name__ == "__main__":
    asyncio.run(main())
