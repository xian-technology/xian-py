# Repository Guidelines

## Scope
- `xian-py` is the external Python SDK for wallets, transactions, RPC interaction, and contract-facing client helpers.
- Keep node internals, ABCI behavior, and contract runtime semantics out of this repo.
- Preserve the public SDK API deliberately while the repo is cleaned up and moved toward a standard package layout.

## Project Layout
- `xian_py/wallet.py`: wallet and key handling.
- `xian_py/transaction.py`: transaction construction and helpers.
- `xian_py/xian.py` and `xian_py/xian_async.py`: synchronous and asynchronous clients.
- `xian_py/crypto.py`, `encoding.py`, `validator.py`: shared SDK utilities.

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
- Validation CI is still pending; add local tests in the same change whenever you touch SDK behavior.
