# Architecture

`xian-py` is the Python SDK for interacting with Xian nodes.

Main areas:

- `src/xian_py/`: SDK transport, wallet, transaction, models, and decoding
- `examples/`: application-facing integration patterns built on top of the SDK
- `tests/`: SDK tests
- `docs/`: internal notes and SDK follow-up items

Dependency direction:

- consumes node APIs from `xian-abci`
- consumes shared deterministic value semantics from `xian-runtime-types`
