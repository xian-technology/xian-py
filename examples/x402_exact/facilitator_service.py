from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

from examples.x402_exact.common import require_wallet, xian_client
from xian_py import (
    XianX402Facilitator,
    XianX402PaymentPayload,
    XianX402PaymentRequirement,
)


class FacilitatorRequest(BaseModel):
    payment_payload: dict[str, Any]
    payment_required: dict[str, Any]


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with xian_client(require_wallet()) as client:
        app.state.client = client
        yield


app = FastAPI(
    title="Xian x402 Facilitator Example",
    description="Verifies and settles native-Xian x402 exact payments.",
    lifespan=lifespan,
)


def _facilitator(request: FacilitatorRequest) -> XianX402Facilitator:
    requirement = XianX402PaymentRequirement.from_payment_required(request.payment_required)
    return XianX402Facilitator(
        client=app.state.client,
        requirement=requirement,
    )


@app.post("/verify")
async def verify(request: FacilitatorRequest) -> dict[str, Any]:
    payload = XianX402PaymentPayload.from_dict(request.payment_payload)
    return _facilitator(request).verify(payload).to_dict()


@app.post("/settle")
async def settle(request: FacilitatorRequest) -> dict[str, Any]:
    payload = XianX402PaymentPayload.from_dict(request.payment_payload)
    result = await _facilitator(request).settle(payload)
    return result.to_dict()
