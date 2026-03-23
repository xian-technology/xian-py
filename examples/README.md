# Examples

## Purpose

This folder contains application-facing examples for integrating `xian-py`
into ordinary software workflows.

## Files

- `fastapi_service.py`: an API-service style integration around `XianAsync`
- `event_worker.py`: a resumable background event consumer
- `admin_job.py`: a simple automation / health-check style job

## Notes

- These examples are intentionally thin and build on the public SDK surface.
- `fastapi_service.py` requires additional packages such as `fastapi` and
  `uvicorn`; the other examples use only the SDK and the standard library.
- All examples use environment variables for node URL, chain ID, and optional
  wallet keys so they can be adapted without editing the files.

## Typical Runs

FastAPI service:

```bash
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
