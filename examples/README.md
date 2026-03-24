# Examples

## Purpose

This folder contains application-facing examples for integrating `xian-py`
into ordinary software workflows.

## Files

- `fastapi_service.py`: an API-service style integration around `XianAsync`
- `event_worker.py`: a resumable background event consumer
- `admin_job.py`: a simple automation / health-check style job
- `credits_ledger/`: the first solution-pack example set and the first deeper
  reference-app slice, built around an application-controlled credits ledger
- `registry_approval/`: the second solution-pack example set and the second
  deeper reference-app slice, built around a shared registry with proposal and
  approval flow
- `workflow_backend/`: the third solution-pack example set and the third
  deeper reference-app slice, built around a shared job-style workflow backend

## Notes

- These examples are intentionally thin and build on the public SDK surface.
- Install the optional app extra before running FastAPI-based examples:
  `uv sync --group dev --extra app`.
- All examples use environment variables for node URL, chain ID, and optional
  wallet keys so they can be adapted without editing the files.

## Typical Runs

FastAPI service:

```bash
uv sync --group dev --extra app
uv run uvicorn examples.fastapi_service:app --reload --app-dir .
```

Event worker:

```bash
uv run python examples/event_worker.py
```

Admin / automation job:

```bash
uv run python examples/admin_job.py
```

Credits Ledger Pack examples:

```bash
uv sync --group dev --extra app
uv run python examples/credits_ledger/admin_job.py
uv run uvicorn examples.credits_ledger.api_service:app --reload --app-dir .
uv run python examples/credits_ledger/projector_worker.py
```

Registry / Approval Pack examples:

```bash
uv sync --group dev --extra app
uv run python examples/registry_approval/admin_job.py
uv run uvicorn examples.registry_approval.api_service:app --reload --app-dir .
uv run python examples/registry_approval/projector_worker.py
```

Workflow Backend Pack examples:

```bash
uv sync --group dev --extra app
uv run python examples/workflow_backend/admin_job.py
uv run uvicorn examples.workflow_backend.api_service:app --reload --app-dir .
uv run python examples/workflow_backend/processor_worker.py
uv run python examples/workflow_backend/projector_worker.py
```
