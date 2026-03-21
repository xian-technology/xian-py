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

## Still Worth Doing

- add typed response models for tx receipts, blocks, events, BDS status, and
  perf status instead of raw dicts
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
