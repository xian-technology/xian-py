# Credits Ledger Examples

## Purpose

This folder contains the SDK-side integration examples for the Credits Ledger
solution pack and the first deeper reference-application slice built on top of
it.

## Files

- `admin_job.py`: bootstrap or administer the ledger contract
- `api_service.py`: small FastAPI surface for balances, issuance, and
  transfers, plus projected activity and summary reads
- `projector_worker.py`: resumable projector that rebuilds a local SQLite read
  model from `Issue`, `Transfer`, and `Burn` events
- `event_worker.py`: compatibility wrapper for `projector_worker.py`
- `projection.py`: SQLite-backed projection store for account activity and
  summary views
- `common.py`: shared environment/config helpers used by these examples

## Environment

Common variables:

- `XIAN_NODE_URL`
- `XIAN_CHAIN_ID`
- `XIAN_WALLET_PRIVATE_KEY`
- `XIAN_CREDITS_CONTRACT` (default: `con_credits_ledger`)

Optional admin/bootstrap variables:

- `XIAN_CREDITS_SOURCE_PATH`
- `XIAN_CREDITS_NAME`
- `XIAN_CREDITS_SYMBOL`
- `XIAN_CREDITS_OPERATOR`
- `XIAN_CREDITS_ISSUE_TO`
- `XIAN_CREDITS_ISSUE_AMOUNT`

Optional worker variable:

- `XIAN_CREDITS_PROJECTION_PATH`

## Typical Runs

Bootstrap or administer the contract:

```bash
uv run python examples/credits_ledger/admin_job.py
```

Run the API service:

```bash
uv run uvicorn examples.credits_ledger.api_service:app --reload --app-dir .
```

Run the event worker:

```bash
uv run python examples/credits_ledger/projector_worker.py
```

The projector backfills from indexed BDS events on first start and maintains a
local SQLite read model that the API service can query for recent activity and
summary views.
