# xian-py

`xian-py` is the external Python SDK for Xian. It provides wallet management,
transaction helpers, RPC clients, and contract-facing convenience methods for
applications that talk to a Xian node.

## Ownership

This repo owns:

- public Python client APIs such as `Xian`, `XianAsync`, and `Wallet`
- transaction construction, encoding, signing, and validation helpers
- SDK-side crypto and contract-time utilities

This repo does not own:

- node internals or ABCI behavior
- contract runtime semantics
- operator lifecycle orchestration

## Installation

```bash
pip install xian-py
```

Optional Ethereum helpers:

```bash
pip install "xian-py[eth]"
```

Optional HD wallet and mnemonic helpers:

```bash
pip install "xian-py[hd]"
```

## Public API

The top-level API now includes the main clients, core exception types, and the
most useful typed result models:

```python
from xian_py import (
    Wallet,
    Xian,
    XianAsync,
    XianException,
    TransactionReceipt,
    TransactionSubmission,
    PerformanceStatus,
    BdsStatus,
    run_sync,
)
```

Synchronous example:

```python
from xian_py import Wallet, Xian

wallet = Wallet()
client = Xian("http://127.0.0.1:26657", wallet=wallet)
balance = client.get_balance(wallet.public_key)
```

Asynchronous example:

```python
import asyncio
from xian_py import Wallet, XianAsync

async def main():
    wallet = Wallet()
    async with XianAsync("http://127.0.0.1:26657", wallet=wallet) as client:
        return await client.get_balance(wallet.public_key)

asyncio.run(main())
```

Use `run_sync(...)` only when you need to bridge async SDK calls into a
strictly synchronous context. Compatibility notes for public module cleanup live
in [`docs/API_COMPATIBILITY.md`](docs/API_COMPATIBILITY.md).

## Transaction Lifecycle

`xian-py` now uses explicit broadcast modes instead of the old ambiguous
`synchronous=True` flag.

Available modes:

- `"async"`: submit to the node and return immediately
- `"checktx"`: wait for mempool admission / `CheckTx`
- `"commit"`: wait for the full `broadcast_tx_commit` response

Example:

```python
result = client.send_tx(
    contract="currency",
    function="transfer",
    kwargs={"amount": 10, "to": recipient},
    mode="checktx",
    wait_for_tx=True,
)
```

Result fields now distinguish the lifecycle stages clearly:

- `submitted`: the node accepted the broadcast request
- `accepted`: `CheckTx` status when the chosen mode exposes it, otherwise `None`
- `finalized`: the tx receipt was retrieved or the commit path finalized it
- `tx_hash`: transaction hash when available

The SDK now returns typed lifecycle objects:

- `TransactionSubmission` from `send_tx`, `send`, `approve`, `submit_contract`
- `TransactionReceipt` from `get_tx` and `wait_for_tx`

Example:

```python
result = client.send_tx(
    contract="currency",
    function="transfer",
    kwargs={"amount": 10, "to": recipient},
    mode="checktx",
    wait_for_tx=True,
)

assert result.submitted is True
assert result.accepted is True
assert result.receipt is not None
print(result.receipt.execution)
```

If you omit `stamps`, the SDK simulates the transaction, estimates stamp usage,
and applies a small configurable headroom before submission.

The async client also keeps a local nonce reservation cache per wallet, so
concurrent submissions from one client instance do not reuse the same nonce.

## Typed Queries

`xian-py` now exposes node perf and indexed BDS reads directly:

```python
perf = client.get_perf_status()
blocks = client.list_blocks(limit=20)
tx = client.get_indexed_tx("ABC123...")
events = client.list_events("currency", "Transfer", limit=50)
history = client.get_state_history("currency.balances:alice")
```

These methods return typed models instead of loose dictionaries:

- `PerformanceStatus`
- `BdsStatus`
- `IndexedBlock`
- `IndexedTransaction`
- `IndexedEvent`
- `StateEntry`

## Structured Errors

The SDK now distinguishes the main error classes:

- `TransportError`
- `RpcError`
- `AbciError`
- `SimulationError`
- `TransactionError`
- `TxTimeoutError`

They all inherit from `XianException`.

## Development

```bash
uv sync --group dev
uv run ruff check .
uv run ruff format --check .
uv run pytest
```
