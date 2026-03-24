# ruff: noqa: I001

from __future__ import annotations

import os

from xian_py import Xian

try:
    from .common import (
        chain_id,
        node_url,
        require_wallet,
        workflow_contract_name,
        workflow_source_path,
    )
except ImportError:
    from common import (  # type: ignore
        chain_id,
        node_url,
        require_wallet,
        workflow_contract_name,
        workflow_source_path,
    )


def _split_workers(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def main() -> None:
    wallet = require_wallet()
    contract_name = workflow_contract_name()

    with Xian(node_url(), chain_id=chain_id(), wallet=wallet) as client:
        status = client.get_node_status()
        print(
            f"Connected to {status.network} at height "
            f"{status.latest_block_height}"
        )

        existing_source = client.get_contract(contract_name)
        if existing_source is None:
            code = workflow_source_path().read_text(encoding="utf-8")
            result = client.submit_contract(
                name=contract_name,
                code=code,
                args={
                    "name": os.environ.get("XIAN_WORKFLOW_NAME", "Job Workflow"),
                    "operator": os.environ.get(
                        "XIAN_WORKFLOW_OPERATOR",
                        wallet.public_key,
                    ),
                },
                mode="commit",
                wait_for_tx=True,
            )
            print(f"Deployed {contract_name}: {result.tx_hash}")
        else:
            print(f"{contract_name} already exists; skipping deployment.")

        workflow = client.contract(contract_name)

        for worker in _split_workers(os.environ.get("XIAN_WORKFLOW_WORKERS")):
            if not workflow.get_state("workers", worker):
                result = workflow.send(
                    "add_worker",
                    account=worker,
                    mode="commit",
                    wait_for_tx=True,
                )
                print(f"Added worker {worker}: {result.tx_hash}")

        item_id = os.environ.get("XIAN_WORKFLOW_ITEM_ID")
        if item_id:
            result = workflow.send(
                "submit_item",
                item_id=item_id,
                kind=os.environ.get("XIAN_WORKFLOW_ITEM_KIND", "job"),
                payload_uri=os.environ.get(
                    "XIAN_WORKFLOW_PAYLOAD_URI",
                    f"https://example.invalid/jobs/{item_id}",
                ),
                metadata_ref=os.environ.get("XIAN_WORKFLOW_METADATA_REF", ""),
                mode="commit",
                wait_for_tx=True,
            )
            print(f"Submitted workflow item {item_id}: {result.tx_hash}")


if __name__ == "__main__":
    main()
