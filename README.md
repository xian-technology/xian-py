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

The intentionally small top-level API is:

```python
from xian_py import Wallet, Xian, XianAsync, XianException, run_sync
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

## Development

```bash
uv sync --group dev
uv run ruff check .
uv run ruff format --check .
uv run pytest
```
