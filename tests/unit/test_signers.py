import pytest

from xian_py.account_master import MasterAccountTransitionDraft
from xian_py.hybrid import AccountTransitionDraft
from xian_py.signers import load_signing_wallet
from xian_py.wallet import Wallet


@pytest.mark.parametrize("draft_class", [AccountTransitionDraft, MasterAccountTransitionDraft])
def test_explicit_signer_import_preserves_identity_and_rejects_wrong_inputs(tmp_path, draft_class):
    legacy = Wallet()
    draft = draft_class("local-test", legacy.public_key, 0)
    path = tmp_path / "active.json"
    password = "strong backup password"
    path.write_text(draft.export_backup("active", password))
    wallet = load_signing_wallet(
        active_backup_file=path,
        backup_password=password,
        expected_address=legacy.public_key,
        chain_id="local-test",
    )
    assert wallet.public_key == legacy.public_key
    assert (
        wallet.sign_transaction(
            dict(
                sender=legacy.public_key,
                chain_id="local-test",
                nonce=0,
                chi_supplied=1000,
                contract="currency",
                function="transfer",
                kwargs={"to": "aa" * 32, "amount": 1},
            )
        )["metadata"]["tx_format"]
        == "xian_account_v1"
    )
    for overrides in (
        {"private_key": legacy.private_key},
        {"backup_password": "wrong"},
        {"expected_address": "bb" * 32},
        {"chain_id": "wrong"},
    ):
        options = dict(active_backup_file=path, backup_password=password)
        options.update(overrides)
        with pytest.raises(Exception):
            load_signing_wallet(**options)
    path.write_text(draft.export_backup("recovery", password))
    with pytest.raises(ValueError, match="cannot spend"):
        load_signing_wallet(active_backup_file=path, backup_password=password)
    assert load_signing_wallet(private_key=legacy.private_key).public_key == legacy.public_key
    with pytest.raises(ValueError, match="exactly one"):
        load_signing_wallet()
