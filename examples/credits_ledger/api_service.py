# ruff: noqa: I001

from __future__ import annotations

from decimal import Decimal

from typing import Any

from examples.contract_json import ContractJsonRoute
from xian_runtime_types.decimal import canonical_fixed
from fastapi import FastAPI, HTTPException

from xian_py import XianAsync

try:
    from .common import (
        chain_id,
        contract_name,
        ensure_submission_succeeded,
        optional_wallet,
        parse_amount,
        node_url,
        projection_path,
    )
    from .projection import CreditsLedgerProjection
except ImportError:
    from common import (  # type: ignore
        chain_id,
        contract_name,
        ensure_submission_succeeded,
        optional_wallet,
        parse_amount,
        node_url,
        projection_path,
    )
    from projection import CreditsLedgerProjection  # type: ignore


def request_amount(payload: dict[str, Any]) -> int | Decimal:
    try:
        return parse_amount(payload["amount"])
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid amount: {exc}") from exc


app = FastAPI(title="Credits Ledger Service")
app.router.route_class = ContractJsonRoute


def _json_amount(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, int):
        return str(value)
    return canonical_fixed(value)


@app.on_event("startup")
async def startup() -> None:
    app.state.client = XianAsync(
        node_url(),
        chain_id=chain_id(),
        wallet=optional_wallet(),
    )
    await app.state.client.__aenter__()
    app.state.projection = CreditsLedgerProjection(
        projection_path(),
        contract_name(),
    )


@app.on_event("shutdown")
async def shutdown() -> None:
    app.state.projection.close()
    await app.state.client.close()


def ledger():
    return app.state.client.contract(contract_name())


def projection() -> CreditsLedgerProjection:
    return app.state.projection


@app.get("/health")
async def health() -> dict[str, Any]:
    status = await app.state.client.get_node_status()
    projection_health = projection().get_health()
    return {
        "network": status.network,
        "height": status.latest_block_height,
        "catching_up": status.catching_up,
        "contract": contract_name(),
        "projection": {
            "path": projection_health["path"],
            "last_event_id": projection_health["last_event_id"],
            "activity_count": projection_health["activity_count"],
            "tracked_accounts": projection_health["tracked_accounts"],
        },
    }


@app.get("/balances/{address}")
async def get_balance(address: str) -> dict[str, Any]:
    return {
        "contract": contract_name(),
        "address": address,
        "balance": _json_amount(await ledger().get_state("balances", address)),
    }


@app.get("/events/transfer")
async def list_transfers(
    after_id: int | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    transfers = (
        await ledger()
        .events("Transfer")
        .list(
            after_id=after_id,
            limit=limit,
        )
    )
    return {
        "contract": contract_name(),
        "count": len(transfers),
        "events": [event.raw for event in transfers],
    }


@app.get("/projection/health")
async def projection_health() -> dict[str, Any]:
    return projection().get_health()


@app.get("/projection/summary")
async def projection_summary() -> dict[str, Any]:
    summary = projection().get_summary()
    return {
        "contract": summary.contract,
        "total_issued": summary.total_issued,
        "total_burned": summary.total_burned,
        "total_transferred": summary.total_transferred,
        "projected_supply": summary.projected_supply,
        "last_event_id": summary.last_event_id,
        "activity_count": summary.activity_count,
        "tracked_accounts": summary.tracked_accounts,
    }


@app.get("/activity/recent")
async def recent_activity(
    limit: int = 50,
    before_id: int | None = None,
) -> dict[str, Any]:
    events = projection().list_activity(limit=limit, before_id=before_id)
    return {
        "contract": contract_name(),
        "count": len(events),
        "events": [event.__dict__ for event in events],
    }


@app.get("/accounts/{address}")
async def get_account(address: str, activity_limit: int = 20) -> dict[str, Any]:
    account_projection = projection().get_account(address)
    recent_events = projection().list_activity(
        address=address,
        limit=activity_limit,
    )
    return {
        "contract": contract_name(),
        "address": address,
        "on_chain_balance": _json_amount(await ledger().get_state("balances", address)),
        "projection": account_projection.__dict__,
        "recent_activity": [event.__dict__ for event in recent_events],
    }


@app.get("/accounts/{address}/activity")
async def get_account_activity(
    address: str,
    limit: int = 50,
    before_id: int | None = None,
) -> dict[str, Any]:
    events = projection().list_activity(
        address=address,
        limit=limit,
        before_id=before_id,
    )
    return {
        "contract": contract_name(),
        "address": address,
        "count": len(events),
        "events": [event.__dict__ for event in events],
    }


@app.post("/issue")
async def issue_credits(payload: dict[str, Any]) -> dict[str, Any]:
    if optional_wallet() is None:
        raise HTTPException(
            status_code=500,
            detail="XIAN_WALLET_PRIVATE_KEY is required for write operations.",
        )
    to = str(payload["to"])
    amount = request_amount(payload)
    try:
        submission = ensure_submission_succeeded(
            await ledger().send(
                "issue",
                to=to,
                amount=amount,
                mode="checktx",
                wait_for_tx=True,
            ),
            "issue credits",
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "tx_hash": submission.tx_hash,
        "to": to,
        "amount": _json_amount(amount),
        "finalized": submission.finalized,
    }


@app.post("/burn")
async def burn_credits(payload: dict[str, Any]) -> dict[str, Any]:
    if optional_wallet() is None:
        raise HTTPException(
            status_code=500,
            detail="XIAN_WALLET_PRIVATE_KEY is required for write operations.",
        )
    amount = request_amount(payload)
    try:
        submission = ensure_submission_succeeded(
            await ledger().send(
                "burn",
                amount=amount,
                mode="checktx",
                wait_for_tx=True,
            ),
            "burn credits",
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "tx_hash": submission.tx_hash,
        "amount": _json_amount(amount),
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
    amount = request_amount(payload)
    try:
        submission = ensure_submission_succeeded(
            await ledger().send(
                "transfer",
                to=to,
                amount=amount,
                mode="checktx",
                wait_for_tx=True,
            ),
            "transfer credits",
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "tx_hash": submission.tx_hash,
        "from": wallet.public_key,
        "to": to,
        "amount": _json_amount(amount),
        "finalized": submission.finalized,
    }
