# xian-py

`xian-py` is the Python SDK for talking to Xian nodes from applications,
workers, automation jobs, and operator tooling.

## Quick Start

Install the SDK:

```bash
pip install xian-py
```

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

## Core Capabilities

- sync and async clients: `Xian` and `XianAsync`
- wallet and signing helpers
- typed transaction submission and receipt models
- readonly contract calls and state queries
- block, event, and indexed-history watchers
- thin helper clients for contracts, tokens, events, and state keys
- reusable projector primitives for SQLite-backed read models

Optional extras:

```bash
pip install "xian-py[app]"
pip install "xian-py[eth]"
pip install "xian-py[hd]"
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
