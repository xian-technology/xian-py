# ruff: noqa: I001

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException

from xian_py import XianAsync

try:
    from .common import (
        chain_id,
        ensure_submission_succeeded,
        node_url,
        optional_wallet,
        projection_path,
        workflow_contract_name,
    )
    from .projection import WorkflowProjection
except ImportError:
    from common import (  # type: ignore
        chain_id,
        ensure_submission_succeeded,
        node_url,
        optional_wallet,
        projection_path,
        workflow_contract_name,
    )
    from projection import WorkflowProjection  # type: ignore

app = FastAPI(title="Workflow Backend Service")


@app.on_event("startup")
async def startup() -> None:
    app.state.client = XianAsync(
        node_url(),
        chain_id=chain_id(),
        wallet=optional_wallet(),
    )
    await app.state.client.__aenter__()
    app.state.projection = WorkflowProjection(
        projection_path(),
        workflow_contract_name(),
    )


@app.on_event("shutdown")
async def shutdown() -> None:
    app.state.projection.close()
    await app.state.client.close()


def workflow():
    return app.state.client.contract(workflow_contract_name())


def projection() -> WorkflowProjection:
    return app.state.projection


@app.get("/health")
async def health() -> dict[str, Any]:
    status = await app.state.client.get_node_status()
    projection_health = projection().get_health()
    return {
        "network": status.network,
        "height": status.latest_block_height,
        "catching_up": status.catching_up,
        "workflow_contract": workflow_contract_name(),
        "projection": {
            "path": projection_health["path"],
            "last_event_id": projection_health["last_event_id"],
            "item_count": projection_health["item_count"],
            "activity_count": projection_health["activity_count"],
        },
    }


@app.get("/projection/health")
async def projection_health() -> dict[str, Any]:
    return projection().get_health()


@app.get("/projection/summary")
async def projection_summary() -> dict[str, Any]:
    summary = projection().get_summary()
    return summary.__dict__


@app.get("/items")
async def list_items(
    limit: int = 50,
    status: str | None = None,
    before_event_id: int | None = None,
) -> dict[str, Any]:
    items = projection().list_items(
        limit=limit,
        status=status,
        before_event_id=before_event_id,
    )
    return {
        "count": len(items),
        "items": [item.__dict__ for item in items],
    }


@app.get("/items/{item_id}")
async def get_item(item_id: str) -> dict[str, Any]:
    item = await workflow().simulate("get_item", item_id=item_id)
    projected = projection().get_item(item_id)
    activity = projection().list_activity(item_id=item_id, limit=20)
    return {
        "item": item,
        "projection": projected.__dict__ if projected is not None else None,
        "recent_activity": [entry.__dict__ for entry in activity],
    }


@app.get("/items/{item_id}/activity")
async def get_item_activity(
    item_id: str,
    limit: int = 50,
    before_id: int | None = None,
) -> dict[str, Any]:
    activity = projection().list_activity(
        item_id=item_id,
        limit=limit,
        before_id=before_id,
    )
    return {
        "item_id": item_id,
        "count": len(activity),
        "events": [entry.__dict__ for entry in activity],
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


@app.post("/items")
async def submit_item(payload: dict[str, Any]) -> dict[str, Any]:
    if optional_wallet() is None:
        raise HTTPException(
            status_code=500,
            detail="XIAN_WALLET_PRIVATE_KEY is required for write operations.",
        )
    try:
        submission = ensure_submission_succeeded(
            await workflow().send(
                "submit_item",
                item_id=str(payload["item_id"]),
                payload_uri=str(payload["payload_uri"]),
                kind=str(payload.get("kind", "job")),
                metadata_ref=str(payload.get("metadata_ref", "")),
                mode="checktx",
                wait_for_tx=True,
            ),
            "submit workflow item",
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"tx_hash": submission.tx_hash, "finalized": submission.finalized}


@app.post("/items/{item_id}/cancel")
async def cancel_item(
    item_id: str, payload: dict[str, Any] | None = None
) -> dict[str, Any]:
    if optional_wallet() is None:
        raise HTTPException(
            status_code=500,
            detail="XIAN_WALLET_PRIVATE_KEY is required for write operations.",
        )
    payload = payload or {}
    try:
        submission = ensure_submission_succeeded(
            await workflow().send(
                "cancel_item",
                item_id=item_id,
                reason=str(payload.get("reason", "")),
                mode="checktx",
                wait_for_tx=True,
            ),
            f"cancel workflow item {item_id}",
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"tx_hash": submission.tx_hash, "finalized": submission.finalized}
