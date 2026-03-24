# Registry / Approval Examples

## Purpose

This folder contains the SDK-side integration examples for the Registry /
Approval solution pack.

## Files

- `admin_job.py`: bootstrap the registry and approval contracts and manage
  signer setup
- `api_service.py`: read records and proposals and submit proposal/approval
  transactions
- `event_worker.py`: consume proposal and registry events with resumable
  cursors
- `common.py`: shared environment/config helpers used by these examples

## Environment

Common variables:

- `XIAN_NODE_URL`
- `XIAN_CHAIN_ID`
- `XIAN_WALLET_PRIVATE_KEY`
- `XIAN_REGISTRY_CONTRACT` (default: `con_registry_records`)
- `XIAN_APPROVAL_CONTRACT` (default: `con_registry_approval`)

Optional admin/bootstrap variables:

- `XIAN_REGISTRY_RECORDS_SOURCE_PATH`
- `XIAN_REGISTRY_APPROVAL_SOURCE_PATH`
- `XIAN_REGISTRY_NAME`
- `XIAN_REGISTRY_OPERATOR`
- `XIAN_REGISTRY_SIGNERS` (comma-separated)
- `XIAN_REGISTRY_THRESHOLD`
- `XIAN_REGISTRY_RECORD_ID`
- `XIAN_REGISTRY_RECORD_OWNER`
- `XIAN_REGISTRY_RECORD_URI`
- `XIAN_REGISTRY_RECORD_CHECKSUM`
- `XIAN_REGISTRY_RECORD_DESCRIPTION`

Optional worker variable:

- `XIAN_REGISTRY_CURSOR_PATH`

## Typical Runs

Bootstrap or administer the contracts:

```bash
uv run python examples/registry_approval/admin_job.py
```

Run the API service:

```bash
uv run uvicorn examples.registry_approval.api_service:app --reload --app-dir .
```

Run the event worker:

```bash
uv run python examples/registry_approval/event_worker.py
```
