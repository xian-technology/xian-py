# API Compatibility

The `src/` migration in this repo is intended to preserve the public import
surface:

- `from xian_py import Xian, XianAsync, Wallet, XianException`
- `from xian_py import run_sync, to_contract_time`

Internal module cleanup can continue later, but package consumers should not
need import-path changes because of the layout migration.
