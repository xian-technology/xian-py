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
        projection_path,
        registry_contract_name,
    )
    from .projection import RegistryApprovalProjection
except ImportError:
    from common import (  # type: ignore
        approval_contract_name,
        chain_id,
        node_url,
        optional_wallet,
        projection_path,
        registry_contract_name,
    )
    from projection import RegistryApprovalProjection  # type: ignore

app = FastAPI(title="Registry Approval Service")


@app.on_event("startup")
async def startup() -> None:
    app.state.client = XianAsync(
        node_url(),
        chain_id=chain_id(),
        wallet=optional_wallet(),
    )
    await app.state.client.__aenter__()
    app.state.projection = RegistryApprovalProjection(
        projection_path(),
        registry_contract=registry_contract_name(),
        approval_contract=approval_contract_name(),
    )


@app.on_event("shutdown")
async def shutdown() -> None:
    app.state.projection.close()
    await app.state.client.close()


def registry():
    return app.state.client.contract(registry_contract_name())


def approval():
    return app.state.client.contract(approval_contract_name())


def projection() -> RegistryApprovalProjection:
    return app.state.projection


@app.get("/health")
async def health() -> dict[str, Any]:
    status = await app.state.client.get_node_status()
    projection_health = projection().get_health()
    return {
        "network": status.network,
        "height": status.latest_block_height,
        "catching_up": status.catching_up,
        "registry_contract": registry_contract_name(),
        "approval_contract": approval_contract_name(),
        "projection": {
            "path": projection_health["path"],
            "last_event_id": projection_health["last_event_id"],
            "proposal_count": projection_health["proposal_count"],
            "record_count": projection_health["record_count"],
        },
    }


@app.get("/projection/health")
async def projection_health() -> dict[str, Any]:
    return projection().get_health()


@app.get("/projection/summary")
async def projection_summary() -> dict[str, Any]:
    summary = projection().get_summary()
    return summary.__dict__


@app.get("/records")
async def list_records(
    limit: int = 50,
    status: str | None = None,
    before_event_id: int | None = None,
) -> dict[str, Any]:
    records = projection().list_records(
        limit=limit,
        status=status,
        before_event_id=before_event_id,
    )
    return {
        "count": len(records),
        "records": [record.__dict__ for record in records],
    }


@app.get("/records/{record_id}")
async def get_record(record_id: str) -> dict[str, Any]:
    record = await registry().simulate("get_record", record_id=record_id)
    projected = projection().get_record(record_id)
    activity = projection().list_activity(record_id=record_id, limit=20)
    return {
        "record": record,
        "projection": projected.__dict__ if projected is not None else None,
        "recent_activity": [entry.__dict__ for entry in activity],
    }


@app.get("/records/{record_id}/activity")
async def get_record_activity(
    record_id: str,
    limit: int = 50,
    before_id: int | None = None,
) -> dict[str, Any]:
    activity = projection().list_activity(
        record_id=record_id,
        limit=limit,
        before_id=before_id,
    )
    return {
        "record_id": record_id,
        "count": len(activity),
        "events": [entry.__dict__ for entry in activity],
    }


@app.get("/proposals")
async def list_proposals(
    limit: int = 50,
    status: str | None = None,
    before_event_id: int | None = None,
    record_id: str | None = None,
) -> dict[str, Any]:
    proposals = projection().list_proposals(
        limit=limit,
        status=status,
        before_event_id=before_event_id,
        record_id=record_id,
    )
    return {
        "count": len(proposals),
        "proposals": [proposal.__dict__ for proposal in proposals],
    }


@app.get("/proposals/pending")
async def list_pending_proposals(limit: int = 50) -> dict[str, Any]:
    proposals = projection().list_proposals(limit=limit, status="pending")
    return {
        "count": len(proposals),
        "proposals": [proposal.__dict__ for proposal in proposals],
    }


@app.get("/proposals/{proposal_id}")
async def get_proposal(proposal_id: int) -> dict[str, Any]:
    proposal = await approval().simulate("get_proposal", proposal_id=proposal_id)
    projected = projection().get_proposal(proposal_id)
    approvals = projection().list_approvals(proposal_id)
    activity = projection().list_activity(proposal_id=proposal_id, limit=20)
    return {
        "proposal": proposal,
        "projection": projected.__dict__ if projected is not None else None,
        "approvals": [approval_event.__dict__ for approval_event in approvals],
        "recent_activity": [entry.__dict__ for entry in activity],
    }


@app.get("/proposals/{proposal_id}/approvals")
async def get_proposal_approvals(proposal_id: int) -> dict[str, Any]:
    approvals = projection().list_approvals(proposal_id)
    return {
        "proposal_id": proposal_id,
        "count": len(approvals),
        "approvals": [approval_event.__dict__ for approval_event in approvals],
    }


@app.get("/activity/recent")
async def recent_activity(
    limit: int = 50,
    before_id: int | None = None,
) -> dict[str, Any]:
    activity = projection().list_activity(limit=limit, before_id=before_id)
    return {
        "count": len(activity),
        "events": [entry.__dict__ for entry in activity],
    }


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
