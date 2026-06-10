from __future__ import annotations

import asyncio

from examples.x402_exact.common import (
    contract_name,
    contract_source_path,
    ensure_submission_succeeded,
    xian_client,
)


async def main() -> None:
    source = contract_source_path().read_text(encoding="utf-8")
    async with xian_client() as client:
        submission = await client.deploy_contract(
            contract_name(),
            source,
            mode="checktx",
            wait_for_tx=True,
        )
    ensure_submission_succeeded(submission, "x402 settlement deployment")
    print(
        f"deployed {contract_name()} tx_hash={submission.tx_hash} finalized={submission.finalized}"
    )


if __name__ == "__main__":
    asyncio.run(main())
