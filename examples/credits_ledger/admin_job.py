# ruff: noqa: I001

from __future__ import annotations

import os

from xian_py import Xian

try:
    from .common import (
        chain_id,
        contract_name,
        contract_source_path,
        require_wallet,
        node_url,
    )
except ImportError:
    from common import (  # type: ignore
        chain_id,
        contract_name,
        contract_source_path,
        require_wallet,
        node_url,
    )


def main() -> None:
    wallet = require_wallet()
    ledger_name = contract_name()

    with Xian(node_url(), chain_id=chain_id(), wallet=wallet) as client:
        status = client.get_node_status()
        print(
            f"Connected to {status.network} at height "
            f"{status.latest_block_height} using {ledger_name}"
        )

        existing_source = client.get_contract(ledger_name)
        if existing_source is None:
            source_path = contract_source_path()
            code = source_path.read_text(encoding="utf-8")
            args = {
                "name": os.environ.get("XIAN_CREDITS_NAME", "App Credits"),
                "symbol": os.environ.get("XIAN_CREDITS_SYMBOL", "CRED"),
                "operator": os.environ.get(
                    "XIAN_CREDITS_OPERATOR",
                    wallet.public_key,
                ),
            }
            result = client.submit_contract(
                name=ledger_name,
                code=code,
                args=args,
                mode="commit",
                wait_for_tx=True,
            )
            print(f"Deployed {ledger_name}: {result.tx_hash}")
        else:
            print(f"{ledger_name} already exists; skipping deployment.")

        ledger = client.contract(ledger_name)
        operator = ledger.state_key("metadata", "operator").get()
        total_supply = ledger.get_state("metadata", "total_supply")
        print(f"Operator: {operator}")
        print(f"Total supply: {total_supply}")

        issue_to = os.environ.get("XIAN_CREDITS_ISSUE_TO")
        issue_amount = os.environ.get("XIAN_CREDITS_ISSUE_AMOUNT")
        if issue_to and issue_amount:
            result = ledger.send(
                "issue",
                to=issue_to,
                amount=issue_amount,
                mode="commit",
                wait_for_tx=True,
            )
            print(
                f"Issued {issue_amount} credits to {issue_to}: {result.tx_hash}"
            )
            print(
                f"Recipient balance: {ledger.get_state('balances', issue_to)}"
            )


if __name__ == "__main__":
    main()
