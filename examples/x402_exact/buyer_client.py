from __future__ import annotations

import asyncio

from examples.x402_exact.common import (
    paid_resource_url,
    payment_amount,
    require_wallet,
)
from xian_py import x402_request


async def main() -> None:
    response = await x402_request(
        "GET",
        paid_resource_url(),
        wallet=require_wallet(),
        max_amount=payment_amount(),
    )
    print(f"status={response.status}")
    if response.payment_payload is not None:
        print(f"payment_id={response.payment_payload.payment_id}")
    if response.payment_response is not None:
        print(f"payment_response={response.payment_response}")
    print(response.text)


if __name__ == "__main__":
    asyncio.run(main())
