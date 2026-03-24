# xian-py

`xian-py` is the external Python SDK for Xian. It provides wallets, RPC
clients, transaction helpers, typed result models, and contract-facing
convenience methods for applications that talk to a Xian node.

## Scope

This repo owns:

- public Python clients such as `Xian`, `XianAsync`, and `Wallet`
- transaction construction, encoding, signing, and validation helpers
- SDK-side typed models, error classes, and utility helpers
- application integration examples for common service and automation patterns

This repo does not own:

- node internals or ABCI behavior
- contract runtime semantics
- operator lifecycle orchestration

## Key Directories

- `src/xian_py/`: client implementations, transaction helpers, models, and wallet code
- `tests/`: SDK behavior and transport coverage
- `docs/`: repo-local notes such as compatibility and backlog items
- `examples/`: service, worker, and automation integration examples built on top of the SDK

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
    AsyncContractClient,
    AsyncEventClient,
    AsyncStateKeyClient,
    AsyncTokenClient,
    ContractClient,
    EventClient,
    RetryPolicy,
    StateKeyClient,
    SubmissionConfig,
    TokenClient,
    TransportConfig,
    Wallet,
    WatcherConfig,
    Xian,
    XianAsync,
    XianClientConfig,
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

## Client Configuration

The SDK now exposes explicit config objects for transport, retry, submission,
and watcher defaults:

```python
from xian_py import (
    RetryPolicy,
    SubmissionConfig,
    TransportConfig,
    WatcherConfig,
    Xian,
    XianClientConfig,
)

config = XianClientConfig(
    transport=TransportConfig(total_timeout_seconds=20.0),
    retry=RetryPolicy(max_attempts=3, initial_delay_seconds=0.25),
    submission=SubmissionConfig(wait_for_tx=True),
    watcher=WatcherConfig(poll_interval_seconds=0.5, batch_limit=200),
)

with Xian("http://127.0.0.1:26657", config=config) as client:
    status = client.get_node_status()
```

Retry policy applies only to read-side operations such as status reads,
queries, tx lookup, and watcher polling. Transaction broadcasts are not retried
automatically.

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

You can set default submission behavior once through
`XianClientConfig.submission` instead of repeating the same per-call options.

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

The default block watcher poll interval comes from `XianClientConfig.watcher`.

Event watching uses the indexed BDS query surface and a stable `after_id`
cursor:

```python
async for event in client.watch_events("currency", "Transfer", after_id=500):
    print(event.id, event.tx_hash, event.data)
```

Use the last seen event `id` as your resume cursor after restarts. Event
watching requires BDS to be enabled on the node.

The default event watcher batch size and poll interval come from
`XianClientConfig.watcher`.

## Application Helper Clients

The SDK now includes thin higher-level helper clients for common application
patterns:

- `client.contract("name")`
- `client.token("currency")`
- `client.events("contract", "EventName")`
- `client.state_key("contract", "variable", *keys)`

These helpers remove repetitive contract names and key construction, but they
still delegate directly to the underlying `Xian` / `XianAsync` primitives.

Contract client example:

```python
ledger = client.contract("con_ledger")

await ledger.send("add_entry", account="alice", amount=5)
balance = await ledger.get_state("balances", "alice")
history = await ledger.state_key("balances", "alice").history(limit=20)
```

Token client example:

```python
currency = client.token()

balance = await currency.balance_of()
await currency.transfer("bob", 10)
await currency.approve("con_dex", amount=100)

async for transfer in currency.transfers().watch(after_id=500):
    print(transfer.data)
```

Event client example:

```python
transfers = client.events("currency", "Transfer")
recent = transfers.list(after_id=500, limit=50)
```

## Integration Examples

The repo now includes application-facing examples under
[`examples/`](examples/README.md):

- `fastapi_service.py`: a small API service that exposes health, balances,
  transfers, and token submission through `XianAsync`
- `event_worker.py`: a resumable background worker that watches indexed events
  with a persisted `after_id` cursor
- `admin_job.py`: a synchronous automation job that checks node, peer, perf,
  and BDS health and exits nonzero on operator-facing problems
- `credits_ledger/`: the first solution-pack example set, showing bootstrap,
  service, projection, and worker patterns for an application-controlled
  credits ledger
- `registry_approval/`: the second solution-pack example set, showing
  bootstrap, proposal, approval, projection, and worker patterns for a shared
  registry
- `workflow_backend/`: the third solution-pack example set, showing
  bootstrap, service, processor, projection, and worker patterns for a
  job-style workflow backend

FastAPI example dependencies are not part of the base package install. Use
your normal app dependency management for `fastapi`, `uvicorn`, and related
framework packages when running that example.

Typical runs:

```bash
uv run uvicorn examples.fastapi_service:app --reload --app-dir .
uv run python examples/event_worker.py
uv run python examples/admin_job.py
```

The `credits_ledger/` example set now goes one step further than the basic
pack walkthrough: it includes a local SQLite projection that can be rebuilt
from indexed BDS events and queried by the example API service for recent
activity and summary views.

The `registry_approval/` example set now follows the same deeper pattern for
approval workflows: indexed events trigger a local SQLite projection, and the
projector hydrates rich proposal and record views from authoritative contract
reads before the example API serves those projected workflow views.

The `workflow_backend/` example set now follows the same deeper pattern for
workflow coordination: a processor worker handles submitted items, a separate
projector rebuilds queue and activity views from indexed events plus
authoritative `get_item` reads, and the example API serves both on-chain and
projected workflow views.

## Structured Errors

The SDK now distinguishes the main error classes:

- `TransportError`
- `RpcError`
- `AbciError`
- `SimulationError`
- `TransactionError`
- `TxTimeoutError`

They all inherit from `XianException`.
