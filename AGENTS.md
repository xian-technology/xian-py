# Repository Guidelines

## Scope
- `xian-py` is the external Python SDK for wallets, transactions, RPC interaction, and contract-facing client helpers.
- Keep node internals, ABCI behavior, and contract runtime semantics out of this repo.
- Preserve the public SDK API deliberately while the repo is cleaned up and moved toward a standard package layout.

## Project Layout
- `src/xian_py/__init__.py`: public SDK exports.
- `src/xian_py/wallet.py`: wallet and key handling.
- `src/xian_py/transaction.py`: transaction construction and helpers.
- `src/xian_py/xian.py` and `src/xian_py/xian_async.py`: synchronous and asynchronous clients.
- `src/xian_py/crypto.py`, `src/xian_py/encoding.py`, `src/xian_py/validator.py`: shared SDK utilities.
- `tests/unit/`: public API, wallet, crypto, encoding, validator, transaction, and client coverage.

## Change Routing
- Do not import private ABCI internals into the SDK.
- If you change request/response behavior, add tests or at least a documented smoke path in the same change.
- Keep compatibility shims in mind when cleaning naming or module-layout issues.

## Validation
- Preferred setup: `uv sync --group dev`
- Lint: `uv run ruff check .`
- Format check: `uv run ruff format --check .`
- Tests: `uv run pytest`

## Notes
- The repo now uses `src/` layout, `pytest`, and `uv`.
- The public API should remain intentionally small: `Xian`, `XianAsync`, `Wallet`, `XianException`, `run_sync`, and contract-time helpers.
