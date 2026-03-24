# ruff: noqa: I001

from __future__ import annotations

import os

from xian_py import Xian

try:
    from .common import (
        approval_contract_name,
        approval_source_path,
        chain_id,
        ensure_submission_succeeded,
        node_url,
        records_source_path,
        registry_contract_name,
        require_wallet,
    )
except ImportError:
    from common import (  # type: ignore
        approval_contract_name,
        approval_source_path,
        chain_id,
        ensure_submission_succeeded,
        node_url,
        records_source_path,
        registry_contract_name,
        require_wallet,
    )


def _split_signers(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def main() -> None:
    wallet = require_wallet()
    registry_name = registry_contract_name()
    approval_name = approval_contract_name()

    with Xian(node_url(), chain_id=chain_id(), wallet=wallet) as client:
        status = client.get_node_status()
        print(
            f"Connected to {status.network} at height "
            f"{status.latest_block_height}"
        )

        registry_source = client.get_contract(registry_name)
        if registry_source is None:
            registry_code = records_source_path().read_text(encoding="utf-8")
            result = ensure_submission_succeeded(
                client.submit_contract(
                    name=registry_name,
                    code=registry_code,
                    args={
                        "name": os.environ.get(
                            "XIAN_REGISTRY_NAME",
                            "Shared Registry",
                        ),
                        "operator": os.environ.get(
                            "XIAN_REGISTRY_OPERATOR",
                            wallet.public_key,
                        ),
                    },
                    mode="checktx",
                    wait_for_tx=True,
                ),
                f"deploy {registry_name}",
            )
            print(f"Deployed {registry_name}: {result.tx_hash}")
        else:
            print(f"{registry_name} already exists; skipping deployment.")

        approval_source = client.get_contract(approval_name)
        if approval_source is None:
            approval_code = approval_source_path().read_text(encoding="utf-8")
            result = ensure_submission_succeeded(
                client.submit_contract(
                    name=approval_name,
                    code=approval_code,
                    args={
                        "registry_contract": registry_name,
                        "operator": os.environ.get(
                            "XIAN_REGISTRY_OPERATOR",
                            wallet.public_key,
                        ),
                        "threshold": int(
                            os.environ.get("XIAN_REGISTRY_THRESHOLD", "1")
                        ),
                    },
                    mode="checktx",
                    wait_for_tx=True,
                ),
                f"deploy {approval_name}",
            )
            print(f"Deployed {approval_name}: {result.tx_hash}")
        else:
            print(f"{approval_name} already exists; skipping deployment.")

        registry = client.contract(registry_name)
        approval = client.contract(approval_name)

        configured_approval = registry.state_key(
            "metadata",
            "approval_contract",
        ).get()
        if configured_approval != approval_name:
            result = ensure_submission_succeeded(
                registry.send(
                    "set_approval_contract",
                    approval_contract=approval_name,
                    mode="checktx",
                    wait_for_tx=True,
                ),
                "configure registry approval contract",
            )
            print(f"Configured approval contract: {result.tx_hash}")

        for signer in _split_signers(os.environ.get("XIAN_REGISTRY_SIGNERS")):
            if not approval.get_state("signers", signer):
                result = ensure_submission_succeeded(
                    approval.send(
                        "add_signer",
                        account=signer,
                        mode="checktx",
                        wait_for_tx=True,
                    ),
                    f"add signer {signer}",
                )
                print(f"Added signer {signer}: {result.tx_hash}")

        desired_threshold = int(os.environ.get("XIAN_REGISTRY_THRESHOLD", "1"))
        current_threshold = approval.state_key("metadata", "threshold").get()
        if current_threshold != desired_threshold:
            result = ensure_submission_succeeded(
                approval.send(
                    "set_threshold",
                    new_threshold=desired_threshold,
                    mode="checktx",
                    wait_for_tx=True,
                ),
                f"set approval threshold to {desired_threshold}",
            )
            print(f"Updated threshold to {desired_threshold}: {result.tx_hash}")

        print(
            f"Registry approval contract: {configured_approval or approval_name}"
        )
        print(
            f"Approval threshold: {approval.state_key('metadata', 'threshold').get()}"
        )

        record_id = os.environ.get("XIAN_REGISTRY_RECORD_ID")
        if record_id:
            result = ensure_submission_succeeded(
                approval.send(
                    "propose_upsert",
                    record_id=record_id,
                    owner=os.environ.get(
                        "XIAN_REGISTRY_RECORD_OWNER", wallet.public_key
                    ),
                    uri=os.environ.get(
                        "XIAN_REGISTRY_RECORD_URI",
                        f"https://example.invalid/records/{record_id}",
                    ),
                    checksum=os.environ.get(
                        "XIAN_REGISTRY_RECORD_CHECKSUM",
                        "checksum-not-set",
                    ),
                    description=os.environ.get(
                        "XIAN_REGISTRY_RECORD_DESCRIPTION",
                        "",
                    ),
                    mode="checktx",
                    wait_for_tx=True,
                ),
                f"submit upsert proposal for {record_id}",
            )
            print(
                f"Submitted upsert proposal for {record_id}: {result.tx_hash}"
            )


if __name__ == "__main__":
    main()
