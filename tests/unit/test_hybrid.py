import json
import os
import subprocess
from pathlib import Path

import pytest

pytest.importorskip("pqcrypto")
pytest.importorskip("cryptography")

from xian_accounts.hybrid import AccountRecord, verify

from xian_py import Wallet, Xian
from xian_py.hybrid import AccountTransitionDraft, HybridWallet, decrypt_backup, encrypt_backup
from xian_py.transaction import canonical_json, create_tx, prepare_transaction

PASSWORD = "correct horse battery staple"


def verified(sender, epoch=0):
    draft = AccountTransitionDraft("local-test", sender, epoch)
    for role in ("active", "recovery"):
        draft.verify_backup(role, draft.export_backup(role, PASSWORD), PASSWORD)
    return draft


def payload(draft, operation="enroll"):
    return dict(
        chain_id="local-test",
        sender=draft.active["sender"],
        nonce=0,
        chi_supplied=1000,
        contract="_accounts",
        function=operation,
        kwargs={"record": draft.active["record"]},
    )


def test_backup_verification_and_mismatches():
    wallet = Wallet("23" * 32)
    draft = AccountTransitionDraft("local-test", wallet.public_key.upper(), 0)
    with pytest.raises(ValueError, match="both"):
        draft.sign(payload(draft), wallet.private_key)
    active = draft.export_backup("active", PASSWORD)
    with pytest.raises(ValueError):
        draft.verify_backup("recovery", active, PASSWORD)
    with pytest.raises(Exception):
        draft.verify_backup("active", active, "wrong password")
    draft.verify_backup("active", active, PASSWORD)
    assert not draft.ready
    draft.verify_backup("recovery", draft.export_backup("recovery", PASSWORD), PASSWORD)
    tx = draft.sign(payload(draft), wallet.private_key)
    record = AccountRecord.from_dict(draft.active["record"])
    assert verify(
        record.active,
        0,
        canonical_json(tx["payload"]).encode(),
        bytes.fromhex(tx["metadata"]["auth"]["active_proof"]),
        role="new_active",
    )
    draft.active["sender"] = "ff" * 32
    assert not draft.ready


def test_recovery_and_sdk_spend_keep_identity_without_old_seed():
    sender = Wallet("23" * 32).public_key.upper()
    old, new = verified(sender), verified(sender, 1)
    recovery = decrypt_backup(old.export_backup("recovery", PASSWORD), PASSWORD)
    tx = new.sign(payload(new, "recover"), recovery)
    record = AccountRecord.from_dict(old.active["record"])
    assert verify(
        record.recovery,
        0,
        canonical_json(tx["payload"]).encode(),
        bytes.fromhex(tx["metadata"]["auth"]["signature"]),
        role="authority",
    )
    wallet = HybridWallet(decrypt_backup(new.export_backup("active", PASSWORD), PASSWORD))
    assert (
        Xian("http://127.0.0.1:26657", chain_id="local-test", wallet=wallet).wallet.public_key
        == sender
    )
    spend = create_tx(
        {
            **payload(new),
            "contract": "currency",
            "function": "transfer",
            "kwargs": {"to": "ff" * 32, "amount": {"__fixed__": "1.5"}},
        },
        wallet,
    )
    assert spend["payload"]["sender"] == sender
    record = AccountRecord.from_dict(new.active["record"])
    assert verify(
        record.active,
        1,
        canonical_json(spend["payload"]).encode(),
        bytes.fromhex(spend["metadata"]["auth"]["signature"]),
    )
    assert prepare_transaction(spend).rpc_hex
    with pytest.raises(ValueError, match="cannot spend"):
        HybridWallet(recovery)


@pytest.mark.skipif(not os.environ.get("XIAN_JS_CLIENT"), reason="optional sibling SDK conformance")
def test_portable_backup_both_directions():
    module = Path(os.environ["XIAN_JS_CLIENT"]).as_uri()
    backup = verified(Wallet("23" * 32).public_key).active
    script = f"""import {{decryptAccountBackup, encryptAccountBackup, HybridAccountSigner, canonicalAccountJson}} from {json.dumps(module)};
import {{readFileSync}} from 'node:fs';
const b=await decryptAccountBackup(readFileSync(0,'utf8'),{json.dumps(PASSWORD)});
console.log(await encryptAccountBackup(b,{json.dumps(PASSWORD)}));"""
    output = subprocess.check_output(
        ["node", "--input-type=module", "-e", script],
        input=encrypt_backup(backup, PASSWORD),
        text=True,
    )
    assert decrypt_backup(output, PASSWORD) == backup
