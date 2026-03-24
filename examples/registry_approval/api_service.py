# ruff: noqa: I001

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException

from xian_py import XianAsync

try:
    from .common import (
        approval_contract_name,
        chain_id,
        node_url,
        optional_wallet,
        registry_contract_name,
    )
except ImportError:
    from common import (  # type: ignore
        approval_contract_name,
        chain_id,
        node_url,
        optional_wallet,
        registry_contract_name,
    )

app = FastAPI(title="Registry Approval Service")


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


def registry():
    return app.state.client.contract(registry_contract_name())


def approval():
    return app.state.client.contract(approval_contract_name())


@app.get("/health")
async def health() -> dict[str, Any]:
    status = await app.state.client.get_node_status()
    return {
        "network": status.network,
        "height": status.latest_block_height,
        "catching_up": status.catching_up,
        "registry_contract": registry_contract_name(),
        "approval_contract": approval_contract_name(),
    }


@app.get("/records/{record_id}")
async def get_record(record_id: str) -> dict[str, Any]:
    record = await registry().simulate("get_record", record_id=record_id)
    return {"record": record}


@app.get("/proposals/{proposal_id}")
async def get_proposal(proposal_id: int) -> dict[str, Any]:
    proposal = await approval().simulate("get_proposal", proposal_id=proposal_id)
    return {"proposal": proposal}


@app.post("/proposals/upsert")
async def propose_upsert(payload: dict[str, Any]) -> dict[str, Any]:
    if optional_wallet() is None:
        raise HTTPException(
            status_code=500,
            detail="XIAN_WALLET_PRIVATE_KEY is required for write operations.",
        )
    submission = await approval().send(
        "propose_upsert",
        record_id=str(payload["record_id"]),
        owner=str(payload["owner"]),
        uri=str(payload["uri"]),
        checksum=str(payload["checksum"]),
        description=str(payload.get("description", "")),
        mode="commit",
        wait_for_tx=True,
    )
    return {"tx_hash": submission.tx_hash, "finalized": submission.finalized}


@app.post("/proposals/revoke")
async def propose_revoke(payload: dict[str, Any]) -> dict[str, Any]:
    if optional_wallet() is None:
        raise HTTPException(
            status_code=500,
            detail="XIAN_WALLET_PRIVATE_KEY is required for write operations.",
        )
    submission = await approval().send(
        "propose_revoke",
        record_id=str(payload["record_id"]),
        reason=str(payload.get("reason", "")),
        mode="commit",
        wait_for_tx=True,
    )
    return {"tx_hash": submission.tx_hash, "finalized": submission.finalized}


@app.post("/proposals/{proposal_id}/approve")
async def approve_proposal(proposal_id: int) -> dict[str, Any]:
    if optional_wallet() is None:
        raise HTTPException(
            status_code=500,
            detail="XIAN_WALLET_PRIVATE_KEY is required for write operations.",
        )
    submission = await approval().send(
        "approve",
        proposal_id=proposal_id,
        mode="commit",
        wait_for_tx=True,
    )
    return {"tx_hash": submission.tx_hash, "finalized": submission.finalized}
