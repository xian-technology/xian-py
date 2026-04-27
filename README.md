# xian-py

`xian-py` is the Python SDK for talking to Xian nodes from applications,
workers, automation jobs, and operator tooling. It exposes a clean
sync / async client surface over node RPCs, indexed BDS queries, and the
CometBFT websocket, plus reusable projector primitives for building local
read models.

The published PyPI package is `xian-tech-py`. The import package remains
`xian_py`.

## Quick Start

Install the SDK:

```bash
pip install xian-tech-py
```

Read state and submit a transaction with the synchronous client:

```python
from xian_py import Wallet, Xian

wallet = Wallet()

with Xian("http://127.0.0.1:26657") as client:
    balance = client.token().balance_of(wallet.public_key)
    receipt = client.token().transfer("bob", 5, wallet=wallet, mode="checktx")
    print(balance, receipt.code)
```

Watch indexed events with the async client:

```python
import asyncio

from xian_py import XianAsync


async def main() -> None:
    async with XianAsync("http://127.0.0.1:26657") as client:
        async for event in client.token().transfers().watch(after_id=0):
            print(event.id, event.data)


asyncio.run(main())
```

For low-latency delivery without BDS-backed cursoring, use raw live websocket
events:

```python
import asyncio

from xian_py import XianAsync


async def main() -> None:
    async with XianAsync("http://127.0.0.1:26657") as client:
        async for event in client.token().transfers().watch_live():
            print(event.tx_hash, event.data)


asyncio.run(main())
```

The SDK derives the websocket endpoint from the RPC URL by default
(`http://127.0.0.1:26657` → `ws://127.0.0.1:26657/websocket`). Override with
`WatcherConfig(websocket_url="ws://rpc-host:26657/websocket")`.

For visibility into transport retries, attach a callback to
`RetryPolicy(on_retry=...)`. The callback receives a typed `RetryEvent` with
the operation kind, attempt number, next backoff delay, and exception.

Optional extras:

```bash
pip install "xian-tech-py[app]"   # FastAPI examples
pip install "xian-tech-py[eth]"   # Ethereum-style key helpers
pip install "xian-tech-py[hd]"    # HD-wallet derivation
```

## Principles

- **One mental model, two clients.** Sync and async clients stay aligned, so
  the same concepts work in scripts, services, and workers.
- **Explicit transaction submission.** Choose a broadcast mode (`async`,
  `checktx`, `commit`) deliberately. The SDK does not hide retry, blocking, or
  finality behavior.
- **Plumbing, not policy.** Read models and projector loops belong in
  application code. The SDK owns the repetitive plumbing (websocket delivery,
  catch-up cursors, raw CometBFT decoding, typed event conversion).
- **Reference apps live alongside, not inside, the wheel.** Examples
  demonstrate how to integrate Xian into Python systems but are not part of
  the published package.
- **No node orchestration.** Operator workflow and node lifecycle live in
  `xian-cli` and `xian-stack`.

## Key Directories

- `src/xian_py/` — clients, wallet helpers, transactions, models, projectors.
  - `xian.py`, `xian_async.py` — primary sync and async clients.
  - `application_clients.py` — thin helper clients (`contract`, `token`,
    `events`, `state_key`).
  - `transaction.py`, `wallet.py`, `crypto.py` — signing, building, and
    submitting transactions.
  - `projectors.py` — reusable polling, ordering, and checkpoint primitives.
  - `models.py` — typed transaction, event, block, and status models.
  - `shielded_relayer.py` — client for the private-submission relayer.
- `examples/` — service, worker, and reference-app examples built on the SDK
  (`credits_ledger/`, `registry_approval/`, `workflow_backend/`,
  `fastapi_service.py`, `event_worker.py`, `admin_job.py`).
- `tests/` — SDK transport, decoding, and integration-shape coverage.
- `docs/` — compatibility notes and SDK backlog items.

## Capabilities

- read current state via ABCI query paths and simulate readonly contract calls
- retrieve preferred contract source and canonical runtime code separately
- create, sign, and broadcast transactions with explicit `async`, `checktx`,
  and `commit` modes; wait for final receipts
- query indexed blocks, transactions, events, state history, and developer
  reward aggregates from BDS-backed nodes
- watch indexed events with websocket live delivery plus resumable BDS cursors
- watch raw live websocket events without BDS when low-latency delivery
  matters more than replayable cursors
- use thin helper clients for common patterns: contract, token, event, and
  state-key access
- build SQLite-backed read models with the shared projector primitives, using
  CometBFT websocket wakeups and BDS cursor reconciliation

Event watching uses the CometBFT websocket directly and expects a BDS-enabled
node for cursorable indexed catch-up and canonical event IDs. Use
`watch_live_events()` or `.watch_live()` when you explicitly want
websocket-only, non-resumable delivery.

## Core API Layers

- `Xian` / `XianAsync` — primary sync and async clients
- `client.contract(...)`, `client.token(...)`, `client.events(...)`,
  `client.state_key(...)` — thin helper clients for common patterns
- Typed models and error classes — predictable result handling instead of raw
  dictionaries
- `EventProjector`, `EventSource`, `SQLiteProjectionState` — reusable
  polling / ordering / checkpoint primitives for local projections
- `Wallet` — Ed25519 signing helper for Xian transactions

## Typical Use Cases

- backend APIs that read state and submit transactions
- background workers that react to indexed events
- automation jobs that reconcile or administer contracts
- local projections that mirror chain activity into an application-owned
  SQLite read model
- operator or integration scripts that need a clean Python surface over node
  RPCs and indexed queries

## Example Paths

- general SDK examples: [examples/README.md](examples/README.md)
- credits-ledger reference app: [examples/credits_ledger/README.md](examples/credits_ledger/README.md)
- registry-approval reference app: [examples/registry_approval/README.md](examples/registry_approval/README.md)
- workflow-backend reference app: [examples/workflow_backend/README.md](examples/workflow_backend/README.md)

## Validation

```bash
uv sync --group dev
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

## Related Docs

- [AGENTS.md](AGENTS.md) — repo-specific guidance for AI agents and contributors
- [docs/README.md](docs/README.md) — index of internal docs
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — major components and dependency direction
- [docs/BACKLOG.md](docs/BACKLOG.md) — open work and follow-ups
- [docs/API_COMPATIBILITY.md](docs/API_COMPATIBILITY.md) — compatibility surface and stability guarantees
- [docs/SDK_REVIEW_BACKLOG.md](docs/SDK_REVIEW_BACKLOG.md) — SDK review queue
