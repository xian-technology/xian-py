from __future__ import annotations

import os
from pathlib import Path

from xian_py import Wallet
from xian_py.models import TransactionSubmission

DEFAULT_REGISTRY_CONTRACT = "con_registry_records"
DEFAULT_APPROVAL_CONTRACT = "con_registry_approval"


def node_url() -> str:
    return os.environ.get("XIAN_NODE_URL", "http://127.0.0.1:26657")


def chain_id() -> str | None:
    return os.environ.get("XIAN_CHAIN_ID")


def registry_contract_name() -> str:
    return os.environ.get(
        "XIAN_REGISTRY_CONTRACT",
        DEFAULT_REGISTRY_CONTRACT,
    )


def approval_contract_name() -> str:
    return os.environ.get(
        "XIAN_APPROVAL_CONTRACT",
        DEFAULT_APPROVAL_CONTRACT,
    )


def require_wallet() -> Wallet:
    private_key = os.environ.get("XIAN_WALLET_PRIVATE_KEY")
    if not private_key:
        raise RuntimeError(
            "XIAN_WALLET_PRIVATE_KEY is required for this example."
        )
    return Wallet(private_key=private_key)


def optional_wallet() -> Wallet | None:
    private_key = os.environ.get("XIAN_WALLET_PRIVATE_KEY")
    if not private_key:
        return None
    return Wallet(private_key=private_key)


def records_source_path() -> Path:
    env_path = os.environ.get("XIAN_REGISTRY_RECORDS_SOURCE_PATH")
    if env_path:
        return Path(env_path).expanduser().resolve()

    workspace_root = Path(__file__).resolve().parents[3]
    return (
        workspace_root
        / "xian-configs"
        / "solutions"
        / "registry-approval"
        / "contracts"
        / "registry_records.s.py"
    )


def approval_source_path() -> Path:
    env_path = os.environ.get("XIAN_REGISTRY_APPROVAL_SOURCE_PATH")
    if env_path:
        return Path(env_path).expanduser().resolve()

    workspace_root = Path(__file__).resolve().parents[3]
    return (
        workspace_root
        / "xian-configs"
        / "solutions"
        / "registry-approval"
        / "contracts"
        / "registry_approval.s.py"
    )


def projection_path() -> Path:
    env_path = os.environ.get("XIAN_REGISTRY_PROJECTION_PATH")
    if env_path:
        return Path(env_path).expanduser().resolve()
    return Path(".registry-approval-projection.sqlite3").resolve()


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
