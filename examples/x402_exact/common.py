from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from xian_py import (
    RetryPolicy,
    SubmissionConfig,
    TransactionSubmission,
    TransportConfig,
    Wallet,
    WatcherConfig,
    XianAsync,
    XianClientConfig,
    XianX402PaymentRequirement,
    xian_network_id,
)

DEFAULT_CONTRACT_NAME = "con_x402_settlement"
DEFAULT_TOKEN_CONTRACT = "currency"


def node_url() -> str:
    return os.environ.get("XIAN_NODE_URL", "http://127.0.0.1:26657")


def chain_id() -> str:
    value = os.environ.get("XIAN_CHAIN_ID")
    if not value:
        raise RuntimeError("XIAN_CHAIN_ID is required for x402 examples.")
    return value


def contract_name() -> str:
    return os.environ.get("XIAN_X402_CONTRACT", DEFAULT_CONTRACT_NAME)


def token_contract() -> str:
    return os.environ.get("XIAN_X402_TOKEN", DEFAULT_TOKEN_CONTRACT)


def payment_amount() -> str:
    return os.environ.get("XIAN_X402_AMOUNT", "0.001")


def paid_resource_url() -> str:
    return os.environ.get(
        "XIAN_X402_RESOURCE_URL",
        "http://127.0.0.1:8000/data",
    )


def require_wallet() -> Wallet:
    private_key = os.environ.get("XIAN_WALLET_PRIVATE_KEY")
    if not private_key:
        raise RuntimeError("XIAN_WALLET_PRIVATE_KEY is required for this example.")
    return Wallet(private_key=private_key)


def pay_to(default: str | None = None) -> str:
    value = os.environ.get("XIAN_X402_PAY_TO") or default
    if not value:
        raise RuntimeError("XIAN_X402_PAY_TO is required when no service wallet is available.")
    return value


def contract_source_path() -> Path:
    env_path = os.environ.get("XIAN_X402_SOURCE_PATH")
    if env_path:
        return Path(env_path).expanduser().resolve()

    workspace_root = Path(__file__).resolve().parents[3]
    return (
        workspace_root
        / "xian-configs"
        / "solutions"
        / "x402-exact"
        / "contracts"
        / "x402_settlement.s.py"
    )


def build_requirement(
    *,
    resource: str,
    seller: str,
) -> XianX402PaymentRequirement:
    return XianX402PaymentRequirement(
        network=xian_network_id(chain_id()),
        asset=token_contract(),
        amount=payment_amount(),
        pay_to=pay_to(seller),
        resource=resource,
        settlement_contract=contract_name(),
        description="Native Xian x402 exact payment",
    )


def build_config() -> XianClientConfig:
    return XianClientConfig(
        transport=TransportConfig(total_timeout_seconds=20.0),
        retry=RetryPolicy(max_attempts=3, initial_delay_seconds=0.25),
        submission=SubmissionConfig(wait_for_tx=True),
        watcher=WatcherConfig(poll_interval_seconds=0.5, batch_limit=200),
    )


@asynccontextmanager
async def xian_client(wallet: Wallet | None = None):
    async with XianAsync(
        node_url(),
        chain_id=chain_id(),
        wallet=wallet or require_wallet(),
        config=build_config(),
    ) as client:
        yield client


def ensure_submission_succeeded(
    submission: TransactionSubmission, action: str
) -> TransactionSubmission:
    if not submission.submitted:
        raise RuntimeError(f"{action} was not submitted: {submission.message}")
    if submission.accepted is False:
        raise RuntimeError(f"{action} was rejected: {submission.message}")
    if not submission.finalized:
        raise RuntimeError(f"{action} was not finalized: {submission.message}")
    if submission.receipt is not None and not submission.receipt.success:
        raise RuntimeError(f"{action} failed: {submission.receipt.message}")
    return submission
