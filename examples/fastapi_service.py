from __future__ import annotations

import os
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from xian_py import (
    RetryPolicy,
    SubmissionConfig,
    TransportConfig,
    Wallet,
    WatcherConfig,
    XianAsync,
    XianClientConfig,
    XianException,
)

NODE_URL = os.getenv("XIAN_NODE_URL", "http://127.0.0.1:26657")
CHAIN_ID = os.getenv("XIAN_CHAIN_ID")
TOKEN_CONTRACT = os.getenv("XIAN_TOKEN_CONTRACT", "currency")
PRIVATE_KEY = os.getenv("XIAN_WALLET_PRIVATE_KEY")


class TransferRequest(BaseModel):
    to_address: str
    amount: Decimal


def _build_config() -> XianClientConfig:
    return XianClientConfig(
        transport=TransportConfig(total_timeout_seconds=20.0),
        retry=RetryPolicy(max_attempts=3, initial_delay_seconds=0.25),
        submission=SubmissionConfig(wait_for_tx=True),
        watcher=WatcherConfig(poll_interval_seconds=0.5, batch_limit=200),
    )


def _build_wallet() -> Wallet:
    if PRIVATE_KEY:
        return Wallet(private_key=PRIVATE_KEY)
    return Wallet()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with XianAsync(
        NODE_URL,
        chain_id=CHAIN_ID,
        wallet=_build_wallet(),
        config=_build_config(),
    ) as client:
        app.state.client = client
        app.state.token = client.token(TOKEN_CONTRACT)
        app.state.read_only = PRIVATE_KEY is None
        yield


app = FastAPI(
    title="Xian FastAPI Example",
    description="Thin API service example built on top of xian-py.",
    lifespan=lifespan,
)


def _serialize_event(event: Any) -> dict[str, Any]:
    return {
        "id": event.id,
        "tx_hash": event.tx_hash,
        "block_height": event.block_height,
        "contract": event.contract,
        "event": event.event,
        "data": event.data,
        "created": event.created,
    }


@app.get("/health")
async def health() -> dict[str, Any]:
    client = app.state.client
    status = await client.get_node_status()
    perf = await client.get_perf_status()
    try:
        bds = await client.get_bds_status()
    except XianException:
        bds = None

    return {
        "node": {
            "moniker": status.moniker,
            "network": status.network,
            "latest_block_height": status.latest_block_height,
            "latest_block_hash": status.latest_block_hash,
            "catching_up": status.catching_up,
        },
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
            }
        ),
        "read_only": app.state.read_only,
    }


@app.get("/balances/{address}")
async def get_balance(address: str) -> dict[str, Any]:
    balance = await app.state.token.balance_of(address)
    return {
        "address": address,
        "token": TOKEN_CONTRACT,
        "balance": str(balance),
    }


@app.get("/transfers")
async def list_transfers(
    after_id: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
) -> dict[str, Any]:
    transfers = await app.state.token.transfers().list(
        after_id=after_id,
        limit=limit,
    )
    return {
        "token": TOKEN_CONTRACT,
        "items": [_serialize_event(event) for event in transfers],
    }


@app.post("/transfers")
async def submit_transfer(request: TransferRequest) -> dict[str, Any]:
    if app.state.read_only:
        raise HTTPException(
            status_code=503,
            detail=(
                "Set XIAN_WALLET_PRIVATE_KEY to enable transfer submission "
                "in this example service."
            ),
        )

    result = await app.state.token.transfer(
        request.to_address,
        request.amount,
    )
    return {
        "submitted": result.submitted,
        "accepted": result.accepted,
        "finalized": result.finalized,
        "tx_hash": result.tx_hash,
        "receipt": None if result.receipt is None else result.receipt.raw,
    }
