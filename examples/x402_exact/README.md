# Xian x402 Exact Example

This example shows a native-Xian x402-style paid HTTP request:

1. the seller API returns `402 Payment Required`
2. the buyer signs a Xian payment payload and permit payload
3. the seller/facilitator settles through `con_x402_settlement`
4. the seller returns the resource with `PAYMENT-RESPONSE`

## Environment

```bash
export XIAN_NODE_URL=http://127.0.0.1:26657
export XIAN_CHAIN_ID=x402-exact-local-1
export XIAN_WALLET_PRIVATE_KEY=<seller-or-facilitator-private-key>
export XIAN_X402_PAY_TO=<seller-public-key>
export XIAN_X402_AMOUNT=0.001
export XIAN_X402_CONTRACT=con_x402_settlement
```

For the buyer command, set `XIAN_WALLET_PRIVATE_KEY` to the buyer key instead.

## Run

Deploy the settlement contract:

```bash
uv run python -m examples.x402_exact.admin_job
```

Run the paid API:

```bash
uv run --extra app uvicorn examples.x402_exact.paid_api_service:app --reload --app-dir .
```

Buy the protected resource:

```bash
export XIAN_X402_RESOURCE_URL=http://127.0.0.1:8000/data
uv run python -m examples.x402_exact.buyer_client
```

The same primitives are also exposed by
`examples.x402_exact.facilitator_service` as `/verify` and `/settle`
endpoints for services that want a separate facilitator process.
