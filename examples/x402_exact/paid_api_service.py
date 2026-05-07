from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from examples.x402_exact.common import (
    build_requirement,
    require_wallet,
    xian_client,
)
from xian_py import (
    PAYMENT_REQUIRED_HEADER,
    PAYMENT_RESPONSE_HEADER,
    PAYMENT_SIGNATURE_HEADER,
    XianX402Facilitator,
    XianX402PaymentPayload,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    wallet = require_wallet()
    async with xian_client(wallet) as client:
        app.state.wallet = wallet
        app.state.client = client
        app.state.cache = {}
        yield


app = FastAPI(
    title="Xian x402 Paid API Example",
    description="Protected API resource that charges through native Xian x402 exact payments.",
    lifespan=lifespan,
)


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "seller": app.state.wallet.public_key,
    }


@app.get("/data")
async def paid_data(request: Request) -> JSONResponse:
    requirement = build_requirement(
        resource=str(request.url),
        seller=app.state.wallet.public_key,
    )
    payment_header = request.headers.get(PAYMENT_SIGNATURE_HEADER)
    if not payment_header:
        return JSONResponse(
            {"error": "payment required"},
            status_code=402,
            headers={
                PAYMENT_REQUIRED_HEADER: requirement.to_payment_required_header()
            },
        )

    payload = XianX402PaymentPayload.from_header(payment_header)
    cached = app.state.cache.get(payload.payment_id)
    if cached is not None:
        return JSONResponse(
            cached["body"],
            headers=cached["headers"],
        )

    facilitator = XianX402Facilitator(
        client=app.state.client,
        requirement=requirement,
    )
    settlement = await facilitator.settle(payload)
    headers = {
        PAYMENT_RESPONSE_HEADER: settlement.to_header(),
    }
    if not settlement.success:
        return JSONResponse(
            {"error": settlement.error or "payment settlement failed"},
            status_code=402,
            headers={
                PAYMENT_REQUIRED_HEADER: requirement.to_payment_required_header(
                    error=settlement.error or "payment settlement failed"
                ),
                **headers,
            },
        )

    body = {
        "message": "paid Xian x402 response",
        "payment_id": payload.payment_id,
        "payer": payload.payer,
        "tx_hash": settlement.transaction,
    }
    app.state.cache[payload.payment_id] = {
        "body": body,
        "headers": headers,
    }
    return JSONResponse(body, headers=headers)
