# API Compatibility

The `src/` migration in this repo preserved the public import surface:

- `from xian_py import Xian, XianAsync, Wallet, XianException`
- `from xian_py import run_sync, to_contract_time`

Internal module cleanup can continue later, but package consumers should not
need import-path changes because of the layout migration.

## Next Breaking SDK Release

The VM-only runtime cleanup is a breaking SDK release. The old
`get_contract(...)` alias has been removed from both `Xian` and `XianAsync`.
Contract submission is source-only: callers pass cleartext source to
`submit_contract(name, code, ...)` or `deploy_contract(name, source, ...)`.
Nodes compile submitted source and persist canonical IR.
Consumers must use the explicit retrieval APIs:

- `get_contract_source(contract)` for canonical contract source
- `get_contract_ir(contract)` for Xian VM IR

Low-level transaction helpers are async-only. Use `Xian` for synchronous
client calls, or call the explicit `*_async` functions from async code.
Ethereum wallet helpers expose `address`; they no longer alias that value as
`public_key`.

## Additive Surface

- `Wallet.from_mnemonic(mnemonic, account_index=0)` derives accounts with the
  canonical Xian mnemonic scheme shared with the browser and mobile wallets.
  It is additive and does not change existing `Wallet` constructor behavior.

Release checklist:

- tag as the next breaking pre-1.0 version, for example `0.5.0`
- call out the removed `get_contract(...)` alias and source-only deployment
  submission path in release notes
- call out removed low-level transaction sync wrappers and the removed
  `EthereumWallet.public_key` address alias
- done: downstream examples use `deploy_contract(...)` / source submission
- keep `/contract_source/<name>` and `/contract_ir/<name>` as the explicit SDK
  retrieval paths for deployed source and canonical IR
