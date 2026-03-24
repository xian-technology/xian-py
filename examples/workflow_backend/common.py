from __future__ import annotations

import os
from pathlib import Path

from xian_py import Wallet

DEFAULT_WORKFLOW_CONTRACT = "con_job_workflow"


def node_url() -> str:
    return os.environ.get("XIAN_NODE_URL", "http://127.0.0.1:26657")


def chain_id() -> str | None:
    return os.environ.get("XIAN_CHAIN_ID")


def workflow_contract_name() -> str:
    return os.environ.get(
        "XIAN_WORKFLOW_CONTRACT",
        DEFAULT_WORKFLOW_CONTRACT,
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


def workflow_source_path() -> Path:
    env_path = os.environ.get("XIAN_WORKFLOW_SOURCE_PATH")
    if env_path:
        return Path(env_path).expanduser().resolve()

    workspace_root = Path(__file__).resolve().parents[3]
    return (
        workspace_root
        / "xian-configs"
        / "solution-packs"
        / "workflow-backend"
        / "contracts"
        / "job_workflow.s.py"
    )


def cursor_path() -> Path:
    env_path = os.environ.get("XIAN_WORKFLOW_CURSOR_PATH")
    if env_path:
        return Path(env_path).expanduser().resolve()
    return Path(".workflow-backend-cursors.json").resolve()


def projection_path() -> Path:
    env_path = os.environ.get("XIAN_WORKFLOW_PROJECTION_PATH")
    if env_path:
        return Path(env_path).expanduser().resolve()
    return Path(".workflow-backend-projection.sqlite3").resolve()
