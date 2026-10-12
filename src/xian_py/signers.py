"""Explicit custody inputs for CLI and service integrations (no enrollment)."""

from pathlib import Path

from xian_py.wallet import Wallet


def load_signing_wallet(
    *,
    private_key: str | None = None,
    active_backup_file: str | Path | None = None,
    backup_password: str | None = None,
    expected_address: str | None = None,
    chain_id: str | None = None,
):
    """Load exactly one legacy key or encrypted active backup, never falling back.

    Hybrid callers install ``xian-tech-py[hybrid]``. Recovery backups are refused.
    No registry changes or credential files are written by this helper.
    """
    if bool(private_key) == bool(active_backup_file):
        raise ValueError("provide exactly one private key or encrypted active backup file")
    if active_backup_file:
        from xian_py.hybrid import HybridWallet, decrypt_backup

        if not backup_password:
            raise ValueError("active backup password is required")
        with Path(active_backup_file).open("rb") as handle:
            data = handle.read(100_001)
        if len(data) > 100_000:
            raise ValueError("account backup too large")
        backup = decrypt_backup(data.decode("utf-8"), backup_password)
        if chain_id is not None and backup["chain_id"] != chain_id:
            raise ValueError("active backup belongs to another chain")
        wallet = HybridWallet(backup)
    else:
        if backup_password:
            raise ValueError("backup password requires an active backup file")
        wallet = Wallet(private_key=private_key)
    if expected_address is not None and wallet.public_key != expected_address:
        raise ValueError("signing wallet does not match the expected account address")
    return wallet
