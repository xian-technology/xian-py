# Permit-based x402 compatibility

The historical `xian_py.x402` message helpers do not provide a settlement path
on the current chain. Currency accepts authenticated transaction calls and has
no permit gateway. This directory contains no deployable settlement example.

Use direct signed currency transfers or approvals. For enrolled accounts, use
the current hybrid signer rather than the original Ed25519 key.
