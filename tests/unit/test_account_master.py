import copy
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

pytest.importorskip("pqcrypto")
pytest.importorskip("cryptography.hazmat.primitives.asymmetric.mldsa")

from xian_accounts.hybrid import AccountRecord, verify

from xian_py import Wallet
from xian_py.account_master import (
    MasterAccountTransitionDraft,
    account_backup_from_master,
    create_account_master,
    export_account_master,
    import_account_master,
    read_account_credential,
    validate_account_master,
)
from xian_py.hybrid import AccountTransitionDraft, HybridWallet, validate_backup
from xian_py.transaction import canonical_json

SENDER = Wallet("23" * 32).public_key.upper()


def payload(draft, operation="enroll"):
    return dict(
        sender=SENDER,
        chain_id="local-test",
        nonce=0,
        chi_supplied=1000,
        contract="_accounts",
        function=operation,
        kwargs={"record": draft.active["record"]},
    )


def test_single_backup_gate_mutation_and_recovery():
    old = MasterAccountTransitionDraft("local-test", SENDER, 0)
    with pytest.raises(ValueError, match="master"):
        old.sign(payload(old), "23" * 32)
    file = old.export_master_backup()
    old.verify_master_backup(file)
    tx = old.sign(payload(old), "23" * 32)
    assert verify(
        AccountRecord.from_dict(old.active["record"]).active,
        0,
        canonical_json(tx["payload"]).encode(),
        bytes.fromhex(tx["metadata"]["auth"]["active_proof"]),
        role="new_active",
    )
    master = import_account_master(file)
    next_draft = MasterAccountTransitionDraft("local-test", SENDER, 1)
    next_draft.verify_master_backup(next_draft.export_master_backup())
    tx = next_draft.sign(
        payload(next_draft, "recover"), account_backup_from_master(master, "recovery")
    )
    assert verify(
        AccountRecord.from_dict(master["record"]).recovery,
        0,
        canonical_json(tx["payload"]).encode(),
        bytes.fromhex(tx["metadata"]["auth"]["signature"]),
        role="authority",
    )
    assert HybridWallet(next_draft.active).public_key == SENDER
    assert next_draft.active["record"] != old.active["record"]
    with pytest.raises(ValueError):
        old.verify_master_backup(file.replace('"master_seed":"', '"master_seed":"0'))
    assert not old.ready
    old.verify_master_backup(file)
    old.active["sender"] = "ff" * 32
    assert not old.ready


def test_context_separation_and_version_confusion():
    m = create_account_master("local-test", SENDER, 7, seed="01" * 32)
    a, r = (account_backup_from_master(m, role) for role in ("active", "recovery"))
    assert len(set([*a["secret"].values(), *r["secret"].values()])) == 4
    for chain, sender, epoch in [
        ("other", SENDER, 7),
        ("local-test", SENDER.lower(), 7),
        ("local-test", SENDER, 8),
    ]:
        assert (
            create_account_master(chain, sender, epoch, seed=m["master_seed"])["record"]
            != m["record"]
        )
    with pytest.raises(ValueError):
        validate_backup({**a, "version": 1})
    for field, value in [("version", True), ("sender", SENDER.lower()), ("master_seed", "02" * 32)]:
        bad = copy.deepcopy(m)
        bad[field] = value
        with pytest.raises(ValueError):
            validate_account_master(bad)


def test_encryption_and_older_backup_imports():
    m = create_account_master("local-test", SENDER, 0)
    encrypted = export_account_master(m, "long enough password")
    assert import_account_master(encrypted, "long enough password") == m
    with pytest.raises(Exception):
        import_account_master(encrypted, "wrong password")
    bad = json.loads(encrypted)
    bad["iterations"] = 10**9
    with pytest.raises(ValueError):
        import_account_master(json.dumps(bad), "long enough password")
    old = AccountTransitionDraft("local-test", SENDER, 0)
    file = old.export_backup("recovery", "long enough password")
    assert read_account_credential(file, "long enough password", "recovery") == old.recovery
    with pytest.raises(ValueError, match="role"):
        read_account_credential(file, "long enough password", "active")


@pytest.mark.skipif(not os.environ.get("XIAN_JS_CLIENT"), reason="explicit sibling SDK conformance")
@pytest.mark.parametrize("chain,epoch", [("local-test", 7), ("local-α-🔑", 2**64 - 1)])
def test_python_javascript_determinism_encryption_and_signature_interop(chain, epoch):
    module = Path(os.environ["XIAN_JS_CLIENT"]).as_uri()
    master = create_account_master(chain, SENDER, epoch, seed="01" * 32)
    encrypted = export_account_master(master, "long enough password")
    script = f"""import {{ createAccountMaster, importAccountMaster, exportAccountMaster, accountBackupFromMaster,
      canonicalAccountJson, HybridAccountSigner }} from {json.dumps(module)};
      import {{readFileSync}} from 'node:fs';
      const master = await importAccountMaster(readFileSync(0,'utf8'), 'long enough password');
      const generated = createAccountMaster(master.chain_id,master.sender,master.record.epoch,'01'.repeat(32));
      if(canonicalAccountJson(master)!==canonicalAccountJson(generated)) throw Error('derivation mismatch');
      const a = accountBackupFromMaster(master,'active');
      const tx = new HybridAccountSigner(a).signTransaction({{payload: {{sender:master.sender,chain_id:master.chain_id,nonce:0,
        chi_supplied:1000,contract:'currency',function:'transfer',kwargs:{{to:'ff'.repeat(32),amount:1}}}}}});
      console.log(canonicalAccountJson({{file: await exportAccountMaster(master,'long enough password'),tx}}));"""
    result = json.loads(
        subprocess.check_output(
            ["node", "--input-type=module", "-e", script], input=encrypted, text=True
        )
    )
    assert import_account_master(result["file"], "long enough password") == master
    tx = result["tx"]
    assert verify(
        AccountRecord.from_dict(master["record"]).active,
        epoch,
        canonical_json(tx["payload"]).encode(),
        bytes.fromhex(tx["metadata"]["auth"]["signature"]),
    )
    # Stable cross-SDK fingerprint, usable by other implementations.
    if chain == "local-test":
        assert (
            hashlib.sha256(canonical_json(master).encode()).hexdigest()
            == "241736b09799e51e179b9a60d33994d15014b8047643cf4d10d5af0ef6500eb0"
        )
