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
- automatic chi estimation using the simulator's exact `chi_used`
- `refresh_nonce()` and `estimate_chi()` helpers
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
- reusable projector / projection primitives:
  - merged indexed-event payload helper
  - shared SQLite cursor state
  - reusable polling projector runner
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
- revisit the validator helper in `validator.py`; it should either consume the
  authoritative `xian-contracting` standard rules or move out of the SDK
  `ast.unparse` based path if possible
- consider renaming `formating.py` to `formatting.py`
