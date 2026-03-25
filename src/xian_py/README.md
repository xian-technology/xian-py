# xian_py

## Purpose

This package contains the public Python SDK for talking to Xian nodes and
building Python services around them.

## Contents

- `xian.py` and `xian_async.py`: the primary sync and async clients
- `application_clients.py`: thin helper clients for contracts, tokens, events,
  and exact state keys
- `transaction.py`: transaction creation, submission helpers, and signing glue
- `models.py` and `exception.py`: typed return models and structured errors
- `projectors.py`: shared event-projector and SQLite checkpoint primitives
- `wallet.py`: Ed25519 wallet wrapper plus optional HD and Ethereum helpers
- `config.py`: transport, retry, submission, and watcher configuration objects

## Notes

- Keep this package aligned with the actual node and indexed-query surfaces the
  stack exposes.
- Prefer thin, composable abstractions over hidden framework behavior.
- If you add a high-level convenience layer here, it should still be possible
  to trace it back to an explicit node/API capability.
