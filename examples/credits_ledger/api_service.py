# ruff: noqa: I001

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException

from xian_py import XianAsync

try:
    from .common import (
        chain_id,
        contract_name,
        optional_wallet,
        node_url,
    )
except ImportError:
    from common import (  # type: ignore
        chain_id,
        contract_name,
        optional_wallet,
        node_url,
    )

app = FastAPI(title="Credits Ledger Service")


@app.on_event("startup")
async def startup() -> None:
    app.state.client = XianAsync(
        node_url(),
        chain_id=chain_id(),
        wallet=optional_wallet(),
    )
    await app.state.client.__aenter__()


@app.on_event("shutdown")
async def shutdown() -> None:
    await app.state.client.close()


def ledger():
    return app.state.client.contract(contract_name())


@app.get("/health")
async def health() -> dict[str, Any]:
    status = await app.state.client.get_node_status()
    return {
        "network": status.network,
        "height": status.latest_block_height,
        "catching_up": status.catching_up,
        "contract": contract_name(),
    }


@app.get("/balances/{address}")
async def get_balance(address: str) -> dict[str, Any]:
    return {
        "contract": contract_name(),
        "address": address,
        "balance": await ledger().get_state("balances", address),
    }


@app.get("/events/transfer")
async def list_transfers(
    after_id: int | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    transfers = await ledger().events("Transfer").list(
        after_id=after_id,
        limit=limit,
    )
    return {
        "contract": contract_name(),
        "count": len(transfers),
        "events": [event.raw for event in transfers],
    }


@app.post("/issue")
async def issue_credits(payload: dict[str, Any]) -> dict[str, Any]:
    if optional_wallet() is None:
        raise HTTPException(
            status_code=500,
            detail="XIAN_WALLET_PRIVATE_KEY is required for write operations.",
        )
    to = str(payload["to"])
    amount = payload["amount"]
    submission = await ledger().send(
        "issue",
        to=to,
        amount=amount,
        mode="commit",
        wait_for_tx=True,
    )
    return {
        "tx_hash": submission.tx_hash,
        "to": to,
        "amount": amount,
        "finalized": submission.finalized,
    }


@app.post("/transfer")
async def transfer_credits(payload: dict[str, Any]) -> dict[str, Any]:
    wallet = optional_wallet()
    if wallet is None:
        raise HTTPException(
            status_code=500,
            detail="XIAN_WALLET_PRIVATE_KEY is required for write operations.",
        )
    to = str(payload["to"])
    amount = payload["amount"]
    submission = await ledger().send(
        "transfer",
        to=to,
        amount=amount,
        mode="commit",
        wait_for_tx=True,
    )
    return {
        "tx_hash": submission.tx_hash,
        "from": wallet.public_key,
        "to": to,
        "amount": amount,
        "finalized": submission.finalized,
    }
