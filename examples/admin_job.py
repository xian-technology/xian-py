from __future__ import annotations

import json
import os
import sys
from typing import Any

from xian_py import RetryPolicy, Xian, XianClientConfig, XianException

NODE_URL = os.getenv("XIAN_NODE_URL", "http://127.0.0.1:26657")
CHAIN_ID = os.getenv("XIAN_CHAIN_ID")
MIN_PEERS = int(os.getenv("XIAN_MIN_PEERS", "0"))
MAX_BDS_HEIGHT_LAG = int(os.getenv("XIAN_MAX_BDS_HEIGHT_LAG", "0"))


def main() -> int:
    config = XianClientConfig(
        retry=RetryPolicy(max_attempts=3, initial_delay_seconds=0.25)
    )

    with Xian(NODE_URL, chain_id=CHAIN_ID, config=config) as client:
        status = client.get_node_status()
        peers = client.get_nodes()
        perf = client.get_perf_status()

        try:
            bds = client.get_bds_status()
        except XianException:
            bds = None

        summary: dict[str, Any] = {
            "node": {
                "moniker": status.moniker,
                "network": status.network,
                "latest_block_height": status.latest_block_height,
                "latest_block_hash": status.latest_block_hash,
                "catching_up": status.catching_up,
            },
            "peer_count": len(peers),
            "perf": {
                "enabled": perf.enabled,
                "tracer_mode": perf.tracer_mode,
            },
            "bds": (
                None
                if bds is None
                else {
                    "worker_running": bds.worker_running,
                    "height_lag": bds.height_lag,
                    "queue_depth": bds.queue_depth,
                    "alerts": bds.alerts,
                }
            ),
        }

        failures: list[str] = []
        if status.catching_up:
            failures.append("node is still catching up")
        if len(peers) < MIN_PEERS:
            failures.append(
                f"peer_count {len(peers)} is below required minimum {MIN_PEERS}"
            )
        if (
            bds is not None
            and MAX_BDS_HEIGHT_LAG > 0
            and bds.height_lag is not None
            and bds.height_lag > MAX_BDS_HEIGHT_LAG
        ):
            failures.append(
                "BDS height lag "
                f"{bds.height_lag} exceeds allowed maximum "
                f"{MAX_BDS_HEIGHT_LAG}"
            )

        print(json.dumps(summary, indent=2, sort_keys=True))

        if failures:
            print(json.dumps({"failures": failures}, indent=2), file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
