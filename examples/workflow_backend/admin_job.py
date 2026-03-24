# ruff: noqa: I001

from __future__ import annotations

import os
from decimal import Decimal

from xian_py import Xian

try:
    from .common import (
        chain_id,
        ensure_submission_succeeded,
        node_url,
        require_wallet,
        workflow_contract_name,
        workflow_source_path,
    )
except ImportError:
    from common import (  # type: ignore
        chain_id,
        ensure_submission_succeeded,
        node_url,
        require_wallet,
        workflow_contract_name,
        workflow_source_path,
    )


def _split_workers(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def _as_decimal(value: object) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def _decimal_to_string(value: Decimal) -> str:
    normalized = value.normalize()
    if normalized == normalized.to_integral():
        return format(normalized.quantize(Decimal("1")), "f")
    return format(normalized, "f").rstrip("0").rstrip(".")


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
            result = ensure_submission_succeeded(
                client.submit_contract(
                    name=contract_name,
                    code=code,
                    args={
                        "name": os.environ.get(
                            "XIAN_WORKFLOW_NAME", "Job Workflow"
                        ),
                        "operator": os.environ.get(
                            "XIAN_WORKFLOW_OPERATOR",
                            wallet.public_key,
                        ),
                    },
                    mode="checktx",
                    wait_for_tx=True,
                ),
                f"deploy {contract_name}",
            )
            print(f"Deployed {contract_name}: {result.tx_hash}")
        else:
            print(f"{contract_name} already exists; skipping deployment.")

        workflow = client.contract(contract_name)

        for worker in _split_workers(os.environ.get("XIAN_WORKFLOW_WORKERS")):
            if not workflow.get_state("workers", worker):
                result = ensure_submission_succeeded(
                    workflow.send(
                        "add_worker",
                        account=worker,
                        mode="checktx",
                        wait_for_tx=True,
                    ),
                    f"add worker {worker}",
                )
                print(f"Added worker {worker}: {result.tx_hash}")

        worker_fund_target = _as_decimal(
            os.environ.get("XIAN_WORKFLOW_WORKER_FUND_AMOUNT", "250")
        )
        native_token = client.token("currency")
        if worker_fund_target > 0:
            for worker in _split_workers(
                os.environ.get("XIAN_WORKFLOW_WORKERS")
            ):
                current_balance = _as_decimal(native_token.balance_of(worker))
                if current_balance >= worker_fund_target:
                    continue
                amount_to_send = worker_fund_target - current_balance
                result = ensure_submission_succeeded(
                    native_token.transfer(
                        worker,
                        _decimal_to_string(amount_to_send),
                        mode="checktx",
                        wait_for_tx=True,
                    ),
                    f"fund worker {worker}",
                )
                print(
                    "Funded worker "
                    f"{worker} to {_decimal_to_string(worker_fund_target)}: "
                    f"{result.tx_hash}"
                )

        item_id = os.environ.get("XIAN_WORKFLOW_ITEM_ID")
        if item_id:
            result = ensure_submission_succeeded(
                workflow.send(
                    "submit_item",
                    item_id=item_id,
                    kind=os.environ.get("XIAN_WORKFLOW_ITEM_KIND", "job"),
                    payload_uri=os.environ.get(
                        "XIAN_WORKFLOW_PAYLOAD_URI",
                        f"https://example.invalid/jobs/{item_id}",
                    ),
                    metadata_ref=os.environ.get(
                        "XIAN_WORKFLOW_METADATA_REF", ""
                    ),
                    mode="checktx",
                    wait_for_tx=True,
                ),
                f"submit workflow item {item_id}",
            )
            print(f"Submitted workflow item {item_id}: {result.tx_hash}")


if __name__ == "__main__":
    main()
