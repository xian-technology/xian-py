# SDK Review Backlog

## Implemented

- explicit transaction broadcast modes: `async`, `checktx`, `commit`
- clearer submission result lifecycle:
  - `submitted`
  - `accepted`
  - `finalized`
- `wait_for_tx(...)` helper on async and sync clients
- local nonce reservation cache per client wallet to prevent concurrent nonce
  reuse
- automatic stamp estimation headroom for implicit stamp selection
- `refresh_nonce()` and `estimate_stamps()` helpers
- block watchers driven from node RPC with resume by height
- event watchers driven from indexed BDS reads with stable `after_id` cursor
- typed `NodeStatus` reads for application and operator workflows
- explicit SDK config objects for transport, retry, submission, and watcher
  defaults
- higher-level application helper clients:
  - contract clients
  - token clients
  - event clients
  - exact state-key clients
- service integration examples:
  - FastAPI service
  - background event worker
  - admin / automation job

## Still Worth Doing

- split `XianException` into transport, RPC, ABCI, simulation, and transaction
  error types
- expose the newer stack surfaces directly in the SDK:
  - BDS-backed block / tx / event queries
  - `/perf_status`
  - `/bds_status`
  - state-history queries
- replace the current per-call sync wrapper model with a persistent background
  transport so the sync client stops creating and destroying event loops for
  each call
- revisit the validator helper in `validator.py`; it should either consume the
  authoritative `xian-contracting` standard rules or move out of the SDK
- replace the remaining `astor` dependency in the decompiler with a stdlib
  `ast.unparse` based path if possible
- clean up naming and ergonomics in wallet helpers, especially the Ethereum
  helper where `public_key` is currently an address
- consider renaming `formating.py` to `formatting.py`
