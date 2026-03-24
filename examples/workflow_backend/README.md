# Workflow Backend Examples

## Purpose

This folder contains the SDK-side integration examples for the Workflow
Backend solution pack and the deeper reference-app slice built on top of it.

## Files

- `admin_job.py`: bootstrap the workflow contract and manage worker setup
- `api_service.py`: submit, query, and cancel workflow items while exposing
  projected queue and activity views
- `processor_worker.py`: claim submitted items and complete or fail them
- `projector_worker.py`: rebuild a local SQLite queue/activity projection from
  indexed events and authoritative contract reads
- `event_worker.py`: compatibility wrapper for `processor_worker.py`
- `projection.py`: SQLite-backed queue and activity projection
- `common.py`: shared environment/config helpers used by these examples

## Environment

Common variables:

- `XIAN_NODE_URL`
- `XIAN_CHAIN_ID`
- `XIAN_WALLET_PRIVATE_KEY`
- `XIAN_WORKFLOW_CONTRACT` (default: `con_job_workflow`)

Optional admin/bootstrap variables:

- `XIAN_WORKFLOW_SOURCE_PATH`
- `XIAN_WORKFLOW_NAME`
- `XIAN_WORKFLOW_OPERATOR`
- `XIAN_WORKFLOW_WORKERS` (comma-separated)
- `XIAN_WORKFLOW_ITEM_ID`
- `XIAN_WORKFLOW_ITEM_KIND`
- `XIAN_WORKFLOW_PAYLOAD_URI`
- `XIAN_WORKFLOW_METADATA_REF`

Optional worker variables:

- `XIAN_WORKFLOW_CURSOR_PATH`
- `XIAN_WORKFLOW_RESULT_PREFIX`
- `XIAN_WORKFLOW_FAIL_REASON`
- `XIAN_WORKFLOW_PROJECTION_PATH`

## Typical Runs

Bootstrap or administer the contract:

```bash
uv run python examples/workflow_backend/admin_job.py
```

Run the API service:

```bash
uv run uvicorn examples.workflow_backend.api_service:app --reload --app-dir .
```

Run the event worker:

```bash
uv run python examples/workflow_backend/processor_worker.py
uv run python examples/workflow_backend/projector_worker.py
```

The processor worker handles submitted workflow items. The projector backfills
from indexed BDS events and keeps a local SQLite queue/activity view in sync
using authoritative `get_item` reads for hydration.
