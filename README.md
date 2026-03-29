# xian-py

`xian-py` is the Python SDK for talking to Xian nodes from applications,
workers, automation jobs, and operator tooling.

## Quick Start

Install the SDK:

```bash
pip install xian-tech-py
```

The published PyPI package name is `xian-tech-py`. The import package remains
`xian_py`.

Read state and send a transaction:

```python
from xian_py import Wallet, Xian

wallet = Wallet()

with Xian("http://127.0.0.1:26657") as client:
    balance = client.token().balance_of(wallet.public_key)
    receipt = client.token().transfer("bob", 5, wallet=wallet, mode="checktx")
    print(balance, receipt.code)
```

Watch indexed events from a BDS-enabled node:

```python
import asyncio

from xian_py import XianAsync


async def main() -> None:
    async with XianAsync("http://127.0.0.1:26657") as client:
        async for event in client.token().transfers().watch(after_id=0):
            print(event.id, event.data)


asyncio.run(main())
```

## Principles

- The SDK keeps sync and async clients aligned so the same concepts work in
  scripts, services, and workers.
- Transaction submission is explicit. Choose a broadcast mode deliberately
  instead of relying on hidden retry or blocking behavior.
- Read models and projector loops belong in application code, but the SDK owns
  the repetitive plumbing for event polling, cursors, and decoding.
- Reference apps and examples live in this repo because they demonstrate how to
  integrate Xian into Python systems, but they are not part of the published
  wheel.

## Key Directories

- `src/xian_py/`: clients, wallet helpers, transactions, models, and projector primitives
- `examples/`: service, worker, and automation examples built on the SDK
- `tests/`: SDK transport, decoding, and integration-shape coverage
- `docs/`: repo-local notes such as compatibility and backlog items

## What It Can Do

- read current state from ABCI query paths and simulate readonly contract calls
- retrieve the preferred contract source and the canonical runtime code separately
- create, sign, and broadcast transactions with explicit `async`, `checktx`,
  and `commit` modes
- wait for final receipts and work with typed transaction, event, block, and
  status models
- query indexed blocks, transactions, events, state-history, and developer
  reward aggregates from BDS-backed nodes
- watch blocks and indexed events with resumable cursors
- use thin helper clients for common patterns such as contract, token, event,
  and state-key access
- build SQLite-backed read models with the shared projector primitives

Indexed event/history queries and projector loops require a BDS-enabled node.

## Core API Layers

- `Xian` and `XianAsync`: the primary sync and async clients
- `client.contract(...)`, `client.token(...)`, `client.events(...)`,
  `client.state_key(...)`: thin helper clients for common application patterns
- typed models and error classes: predictable result handling instead of raw
  dictionaries everywhere
- `EventProjector`, `EventSource`, `SQLiteProjectionState`:
  reusable polling/order/checkpoint primitives for local projections
- `Wallet`: Ed25519 signing helper for Xian transactions

## Typical Use Cases

- backend APIs that read state and submit transactions
- background workers that react to indexed events
- automation jobs that reconcile or administer contracts
- local projections that mirror chain activity into an application-owned SQLite
  read model
- operator or integration scripts that need a clean Python surface over node
  RPCs and indexed queries

Optional extras:

```bash
pip install "xian-tech-py[app]"
pip install "xian-tech-py[eth]"
pip install "xian-tech-py[hd]"
```

Use the `app` extra for the included FastAPI-based examples.

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

- [AGENTS.md](AGENTS.md)
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- [docs/BACKLOG.md](docs/BACKLOG.md)
- [docs/API_COMPATIBILITY.md](docs/API_COMPATIBILITY.md)
