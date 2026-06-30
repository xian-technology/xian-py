# Repository Guidelines

## Shared Convention
- Follow the shared repo convention in `xian-meta/docs/REPO_CONVENTIONS.md`.
- Keep this repo aligned with that standard for stable root docs, backlog placement, and folder-level README entrypoints.
- Follow the shared change workflow in `xian-meta/docs/CHANGE_WORKFLOW.md`.
- Before push, review API/docs impact in `xian-docs-web` and run the local validation path from this file.

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
- Prefer explicit breaking cleanup over compatibility shims when an API has been
  intentionally retired.

## Validation
- Preferred setup: `uv sync --group dev --extra compile`
- Lint: `uv run ruff check .`
- Format check: `uv run ruff format --check .`
- Tests: `uv run pytest`

## Notes
- The repo now uses `src/` layout, `pytest`, and `uv`.
- The public API should remain intentionally small: `Xian`, `XianAsync`, `Wallet`, `XianException`, `run_sync`, and contract-time helpers.

## Shared Agent Practices
- Keep changes clean, modular, and professional. Prefer small, cohesive modules, clear naming, explicit boundaries, and tests over quick patches.
- When code behavior, public APIs, user workflows, operator workflows, or configuration semantics change, check whether `../xian-docs-web` needs corresponding documentation updates. If this repo is `xian-docs-web`, update the relevant published docs in place. Write durable user/developer documentation, not a changelog entry.
- For codebase questions, use the local graph first when `graphify-out/graph.json` exists: run `graphify query "<question>"`; use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts.
- Dirty `graphify-out/` files are expected after hooks or incremental updates and are not a reason to skip graphify. Only skip graphify if the task is about stale or incorrect graph output, or the user explicitly says not to use it.
- Use `graphify-out/wiki/index.md` for broad navigation when it exists. Read `graphify-out/GRAPH_REPORT.md` only for broad architecture review or when query/path/explain do not surface enough context.
- For any non-trivial code change, update the local graph before final verification when `graphify-out/graph.json` exists. Run `graphify update .` from the repo root, or `graphify update . --force` when deletions or refactors intentionally shrink the graph.
- After updating the graph, check cross-repo impact before finishing: query the local graph, inspect paths with `graphify path` or `graphify explain`, and note any affected sibling repos.
- If graphify or dependency analysis shows affected sibling repos, update those repos in the same change when the impact is real and the fix is in scope.
- Treat `graphify-out/` as a generated local artifact. Do not commit it.
