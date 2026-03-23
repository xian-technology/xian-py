# xian-py

`xian-py` is the external Python SDK for Xian. It provides wallets, RPC
clients, transaction helpers, typed result models, and contract-facing
convenience methods for applications that talk to a Xian node.

## Scope

This repo owns:

- public Python clients such as `Xian`, `XianAsync`, and `Wallet`
- transaction construction, encoding, signing, and validation helpers
- SDK-side typed models, error classes, and utility helpers

This repo does not own:

- node internals or ABCI behavior
- contract runtime semantics
- operator lifecycle orchestration

## Key Directories

- `src/xian_py/`: client implementations, transaction helpers, models, and wallet code
- `tests/`: SDK behavior and transport coverage
- `docs/`: repo-local notes such as compatibility and backlog items

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

## Installation

```bash
pip install xian-py
```

Optional extras:

```bash
pip install "xian-py[eth]"
pip install "xian-py[hd]"
```

## Public API

```python
from xian_py import (
    Wallet,
    Xian,
    XianAsync,
    XianException,
    NodeStatus,
    TransactionReceipt,
    TransactionSubmission,
    PerformanceStatus,
    BdsStatus,
    run_sync,
)
```

`Xian` keeps a persistent background event loop and HTTP session for the life
of the client. Prefer using it as a context manager or calling `close()`
explicitly when you are done.

## Transaction Lifecycle

`xian-py` uses explicit broadcast modes instead of the old
`synchronous=True` flag:

- `"async"`: submit and return immediately
- `"checktx"`: wait for mempool admission
- `"commit"`: wait for the full commit response

If `stamps` are omitted, the SDK simulates, estimates usage, and applies a
small headroom before submission. The async client also keeps a local nonce
reservation cache so concurrent submissions from one client instance do not
reuse the same nonce.

## Typed Queries

`xian-py` now exposes node status, node perf, and indexed BDS reads directly:

```python
status = client.get_node_status()
perf = client.get_perf_status()
blocks = client.list_blocks(limit=20)
tx = client.get_indexed_tx("ABC123...")
events = client.list_events("currency", "Transfer", limit=50)
history = client.get_state_history("currency.balances:alice")
```

These methods return typed models instead of loose dictionaries:

- `NodeStatus`
- `PerformanceStatus`
- `BdsStatus`
- `IndexedBlock`
- `IndexedTransaction`
- `IndexedEvent`
- `StateEntry`

## Watchers

The SDK now includes polling-based watcher helpers for long-running Python
services.

Block watching uses raw node RPC and does not require BDS:

```python
async for block in client.watch_blocks(start_height=101):
    print(block.height, block.tx_count)
```

If `start_height` is omitted, block watching starts at the next block after the
current node head.

Event watching uses the indexed BDS query surface and a stable `after_id`
cursor:

```python
async for event in client.watch_events("currency", "Transfer", after_id=500):
    print(event.id, event.tx_hash, event.data)
```

Use the last seen event `id` as your resume cursor after restarts. Event
watching requires BDS to be enabled on the node.

## Structured Errors

The SDK now distinguishes the main error classes:

- `TransportError`
- `RpcError`
- `AbciError`
- `SimulationError`
- `TransactionError`
- `TxTimeoutError`

They all inherit from `XianException`.
