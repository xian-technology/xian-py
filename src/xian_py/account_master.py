"""Portable single-master backups. See ACCOUNT_MASTER_BACKUP.md in xian-meta."""

import copy
import hashlib
import json
import secrets

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.mldsa import MLDSA65PrivateKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from nacl.signing import SigningKey
from xian_accounts.hybrid import AccountRecord, exact_dict, hex_bytes, uint64

from xian_py.hybrid import AccountTransitionDraft, decrypt_backup, validate_backup
from xian_py.transaction import canonical_json

_DOMAIN = b"XIAN-ACCOUNT-MASTER\0v1"
_AAD = b"XIAN-ACCOUNT-MASTER-BACKUP\0v1"


def _material(chain, sender, epoch, seed):
    if type(chain) is not str or not 1 <= len(chain) <= 256 or type(sender) is not str:
        raise ValueError("invalid master identity")
    hex_bytes(sender.lower(), 32)
    uint64(epoch)
    root = hex_bytes(seed, 32)
    pairs = {}
    for role in ("active", "recovery"):

        def derive(algorithm):
            return HKDF(
                algorithm=hashes.SHA512(),
                length=32,
                salt=_DOMAIN,
                info=canonical_json([chain, sender, epoch, role, algorithm]).encode(),
            ).derive(root)

        ed, pq = derive("ed25519"), derive("ml-dsa-65")
        pairs[role] = {
            "public": {
                "ed25519": bytes(SigningKey(ed).verify_key).hex(),
                "ml_dsa_65": MLDSA65PrivateKey.from_seed_bytes(pq)
                .public_key()
                .public_bytes_raw()
                .hex(),
            },
            "secret": {"ed25519_seed": ed.hex(), "ml_dsa_65": pq.hex()},
        }
    record = AccountRecord.from_dict(
        {
            "version": 1,
            "epoch": epoch,
            "active": pairs["active"]["public"],
            "recovery": pairs["recovery"]["public"],
        }
    ).to_dict()
    return {
        role: validate_backup(
            {
                "version": 2,
                "kind": "xian-account-backup",
                "chain_id": chain,
                "sender": sender,
                "record": record,
                "role": role,
                "secret": pairs[role]["secret"],
            }
        )
        for role in ("active", "recovery")
    }


def create_account_master(chain_id, sender, epoch, *, seed=None):
    seed = secrets.token_hex(32) if seed is None else seed
    record = _material(chain_id, sender, epoch, seed)["active"]["record"]
    return {
        "version": 1,
        "kind": "xian-account-master",
        "chain_id": chain_id,
        "sender": sender,
        "record": record,
        "master_seed": seed,
    }


def validate_account_master(value):
    exact_dict(value, {"version", "kind", "chain_id", "sender", "record", "master_seed"})
    if (
        type(value["version"]) is not int
        or value["version"] != 1
        or value["kind"] != "xian-account-master"
    ):
        raise ValueError("unsupported master backup")
    record = AccountRecord.from_dict(value["record"])
    material = _material(value["chain_id"], value["sender"], record.epoch, value["master_seed"])
    if material["active"]["record"] != value["record"]:
        raise ValueError("master does not match account keys")
    return copy.deepcopy(value)


def account_backup_from_master(value, role):
    if role not in ("active", "recovery"):
        raise ValueError("invalid account role")
    master = validate_account_master(value)
    return _material(
        master["chain_id"], master["sender"], master["record"]["epoch"], master["master_seed"]
    )[role]


def export_account_master(value, password=""):
    """Without a password the file IS the secret. Store it offline."""
    clear = canonical_json(validate_account_master(value))
    if not password:
        return clear
    if len(password) < 12:
        raise ValueError("use a backup password of at least 12 characters")
    salt, iv = secrets.token_bytes(16), secrets.token_bytes(12)
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600_000, 32)
    return json.dumps(
        {
            "version": 1,
            "kind": "xian-account-master-encrypted",
            "iterations": 600_000,
            "salt": salt.hex(),
            "iv": iv.hex(),
            "ciphertext": AESGCM(key).encrypt(iv, clear.encode(), _AAD).hex(),
        }
    )


def _read(text):
    if type(text) is not str or len(text) > 100_000:
        raise ValueError("account backup too large")
    value = json.loads(text)
    if type(value) is not dict:
        raise ValueError("invalid backup")
    return value


def import_account_master(text, password=""):
    value = _read(text)
    if value.get("kind") == "xian-account-master":
        return validate_account_master(value)
    exact_dict(value, {"version", "kind", "iterations", "salt", "iv", "ciphertext"})
    if (
        type(value["version"]) is not int
        or value["version"] != 1
        or value["kind"] != "xian-account-master-encrypted"
        or type(value["iterations"]) is not int
        or value["iterations"] != 600_000
        or type(value["ciphertext"]) is not str
        or not 32 <= len(value["ciphertext"]) <= 100_000
    ):
        raise ValueError("invalid encrypted master backup")
    salt, iv = hex_bytes(value["salt"], 16), hex_bytes(value["iv"], 12)
    ciphertext = hex_bytes(value["ciphertext"], len(value["ciphertext"]) // 2)
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600_000, 32)
    return validate_account_master(_read(AESGCM(key).decrypt(iv, ciphertext, _AAD).decode()))


def read_account_credential(text, password, role):
    value = _read(text)
    backup = (
        account_backup_from_master(import_account_master(text, password), role)
        if value.get("kind") in ("xian-account-master", "xian-account-master-encrypted")
        else decrypt_backup(text, password)
    )
    if backup["role"] != role:
        raise ValueError("wrong backup role")
    return backup


class MasterAccountTransitionDraft(AccountTransitionDraft):
    """Recommended transition: reopen ONE saved master backup before signing."""

    def __init__(self, chain_id, sender, epoch):
        self._master = create_account_master(chain_id, sender, epoch)
        self.active = account_backup_from_master(self._master, "active")
        self.recovery = account_backup_from_master(self._master, "recovery")
        self._verified = {}
        self._verified_master = None

    def export_master_backup(self, password=""):
        return export_account_master(self._master, password)

    def verify_master_backup(self, text, password=""):
        self._verified_master = None
        master = import_account_master(text, password)
        if (
            master != self._master
            or account_backup_from_master(master, "active") != self.active
            or account_backup_from_master(master, "recovery") != self.recovery
        ):
            raise ValueError("not the master backup for this draft")
        self._verified_master = self._fingerprint()

    def _fingerprint(self):
        return canonical_json([self._master, self.active, self.recovery])

    @property
    def ready(self):
        return self._verified_master == self._fingerprint()

    def sign(self, payload, authority):
        if not self.ready:
            raise ValueError("reopen and verify the new master backup first")
        return super().sign(payload, authority)
