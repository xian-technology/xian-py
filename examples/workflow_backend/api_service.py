# ruff: noqa: I001

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException

from xian_py import XianAsync

try:
    from .common import (
        chain_id,
        node_url,
        optional_wallet,
        workflow_contract_name,
    )
except ImportError:
    from common import (  # type: ignore
        chain_id,
        node_url,
        optional_wallet,
        workflow_contract_name,
    )

app = FastAPI(title="Workflow Backend Service")


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


def workflow():
    return app.state.client.contract(workflow_contract_name())


@app.get("/health")
async def health() -> dict[str, Any]:
    status = await app.state.client.get_node_status()
    return {
        "network": status.network,
        "height": status.latest_block_height,
        "catching_up": status.catching_up,
        "workflow_contract": workflow_contract_name(),
    }


@app.get("/items/{item_id}")
async def get_item(item_id: str) -> dict[str, Any]:
    item = await workflow().simulate("get_item", item_id=item_id)
    return {"item": item}


@app.post("/items")
async def submit_item(payload: dict[str, Any]) -> dict[str, Any]:
    if optional_wallet() is None:
        raise HTTPException(
            status_code=500,
            detail="XIAN_WALLET_PRIVATE_KEY is required for write operations.",
        )
    submission = await workflow().send(
        "submit_item",
        item_id=str(payload["item_id"]),
        payload_uri=str(payload["payload_uri"]),
        kind=str(payload.get("kind", "job")),
        metadata_ref=str(payload.get("metadata_ref", "")),
        mode="commit",
        wait_for_tx=True,
    )
    return {"tx_hash": submission.tx_hash, "finalized": submission.finalized}


@app.post("/items/{item_id}/cancel")
async def cancel_item(item_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    if optional_wallet() is None:
        raise HTTPException(
            status_code=500,
            detail="XIAN_WALLET_PRIVATE_KEY is required for write operations.",
        )
    payload = payload or {}
    submission = await workflow().send(
        "cancel_item",
        item_id=item_id,
        reason=str(payload.get("reason", "")),
        mode="commit",
        wait_for_tx=True,
    )
    return {"tx_hash": submission.tx_hash, "finalized": submission.finalized}
