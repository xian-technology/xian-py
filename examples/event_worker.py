from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from xian_py import RetryPolicy, WatcherConfig, XianAsync, XianClientConfig

NODE_URL = os.getenv("XIAN_NODE_URL", "http://127.0.0.1:26657")
CHAIN_ID = os.getenv("XIAN_CHAIN_ID")
TOKEN_CONTRACT = os.getenv("XIAN_TOKEN_CONTRACT", "currency")
EVENT_NAME = os.getenv("XIAN_EVENT_NAME", "Transfer")
CURSOR_PATH = Path(
    os.getenv("XIAN_EVENT_CURSOR_PATH", ".xian-transfer-cursor")
)


def read_cursor() -> int | None:
    if not CURSOR_PATH.exists():
        return None
    raw = CURSOR_PATH.read_text(encoding="utf-8").strip()
    if not raw:
        return None
    return int(raw)


def write_cursor(cursor: int) -> None:
    CURSOR_PATH.write_text(f"{cursor}\n", encoding="utf-8")


def serialize_event(event: Any) -> dict[str, Any]:
    return {
        "id": event.id,
        "tx_hash": event.tx_hash,
        "block_height": event.block_height,
        "contract": event.contract,
        "event": event.event,
        "data": event.data,
        "created": event.created,
    }


async def main() -> None:
    config = XianClientConfig(
        retry=RetryPolicy(max_attempts=3, initial_delay_seconds=0.25),
        watcher=WatcherConfig(poll_interval_seconds=1.0, batch_limit=100),
    )
    cursor = read_cursor()

    async with XianAsync(
        NODE_URL,
        chain_id=CHAIN_ID,
        config=config,
    ) as client:
        event_client = client.events(TOKEN_CONTRACT, EVENT_NAME)
        print(
            json.dumps(
                {
                    "message": "starting worker",
                    "contract": TOKEN_CONTRACT,
                    "event": EVENT_NAME,
                    "after_id": cursor,
                },
                sort_keys=True,
            )
        )
        async for event in event_client.watch(after_id=cursor):
            if event.id is None:
                continue
            print(json.dumps(serialize_event(event), sort_keys=True))
            write_cursor(event.id)
            cursor = event.id


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("worker stopped")
