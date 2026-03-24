# ruff: noqa: I001

from __future__ import annotations

import asyncio
import json
import os

from xian_py import XianAsync

try:
    from .common import (
        chain_id,
        cursor_path,
        node_url,
        require_wallet,
        workflow_contract_name,
    )
except ImportError:
    from common import (  # type: ignore
        chain_id,
        cursor_path,
        node_url,
        require_wallet,
        workflow_contract_name,
    )

MONITOR_EVENT_NAMES = (
    "ItemClaimed",
    "ItemCompleted",
    "ItemFailed",
    "ItemCancelled",
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


async def follow_event(
    client: XianAsync,
    event_name: str,
    cursors: dict[str, int],
) -> None:
    event_client = client.contract(workflow_contract_name()).events(event_name)
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


async def process_submitted_items(
    client: XianAsync, cursors: dict[str, int]
) -> None:
    workflow = client.contract(workflow_contract_name())
    async for event in workflow.events("ItemSubmitted").watch(
        after_id=cursors.get("processor:ItemSubmitted")
    ):
        data = event.data or {}
        item_id = str(data["item_id"])
        print(
            json.dumps(
                {
                    "event": "ItemSubmitted",
                    "id": event.id,
                    "tx_hash": event.tx_hash,
                    "data": data,
                },
                sort_keys=True,
            )
        )
        try:
            await workflow.send(
                "claim_item",
                item_id=item_id,
                mode="commit",
                wait_for_tx=True,
            )
            fail_reason = os.environ.get("XIAN_WORKFLOW_FAIL_REASON")
            if fail_reason:
                await workflow.send(
                    "fail_item",
                    item_id=item_id,
                    reason=fail_reason,
                    mode="commit",
                    wait_for_tx=True,
                )
            else:
                result_prefix = os.environ.get(
                    "XIAN_WORKFLOW_RESULT_PREFIX",
                    "https://example.invalid/results/",
                )
                await workflow.send(
                    "complete_item",
                    item_id=item_id,
                    result_uri=f"{result_prefix}{item_id}",
                    mode="commit",
                    wait_for_tx=True,
                )
        except Exception as exc:
            print(json.dumps({"item_id": item_id, "error": str(exc)}))

        if event.id is not None:
            cursors["processor:ItemSubmitted"] = event.id
            save_cursors(cursors)


async def main() -> None:
    cursors = load_cursors()
    async with XianAsync(
        node_url(),
        chain_id=chain_id(),
        wallet=require_wallet(),
    ) as client:
        await asyncio.gather(
            process_submitted_items(client, cursors),
            *(
                follow_event(client, event_name, cursors)
                for event_name in MONITOR_EVENT_NAMES
            ),
        )


if __name__ == "__main__":
    asyncio.run(main())
