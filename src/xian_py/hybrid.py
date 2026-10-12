"""Opt-in production hybrid account wallets and portable encrypted backups.

Import from this submodule. Install xian-tech-py[hybrid]. Network activation and
atomic custody persistence remain explicit responsibilities of the application.
"""

import copy
import hashlib
import json
import secrets

from nacl.signing import SigningKey
from xian_accounts.hybrid import (
    AUTH_DOMAIN,
    ENROLL_SCHEME,
    SCHEME,
    TX_FORMAT,
    AccountRecord,
    PublicKeys,
    backend,
    enrollment_transcript,
    exact_dict,
    hex_bytes,
    sign,
    signing_transcript,
    verify,
)

from xian_py.transaction import canonical_json

_AAD = b"XIAN-ACCOUNT-BACKUP\0v1"


def _pair():
    seed = secrets.token_bytes(32)
    public, private = backend().generate_keypair()
    return (
        PublicKeys(bytes(SigningKey(seed).verify_key), public),
        {"ed25519_seed": seed.hex(), "ml_dsa_65": private.hex()},
    )


def validate_backup(value: dict) -> dict:
    exact_dict(value, {"version", "kind", "chain_id", "sender", "record", "role", "secret"})
    if (
        type(value["version"]) is not int
        or value["version"] not in (1, 2)
        or value["kind"] != "xian-account-backup"
        or type(value["chain_id"]) is not str
        or not 1 <= len(value["chain_id"]) <= 256
        or value["role"] not in ("active", "recovery")
        or type(value["sender"]) is not str
    ):
        raise ValueError("invalid account backup")
    hex_bytes(value["sender"].lower(), 32)
    record = AccountRecord.from_dict(value["record"])
    secret = exact_dict(value["secret"], {"ed25519_seed", "ml_dsa_65"})
    # A self-verified signature checks both private/public pairs, including ML-DSA.
    _sign_secret(
        getattr(record, value["role"]),
        record.epoch,
        b"XIAN-BACKUP-KEY-CHECK",
        ed_seed=hex_bytes(secret["ed25519_seed"], 32),
        pq_secret=hex_bytes(secret["ml_dsa_65"], 32 if value["version"] == 2 else 4032),
    )
    return copy.deepcopy(value)


def encrypt_backup(value: dict, password: str) -> str:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    if len(password) < 12:
        raise ValueError("use a backup password of at least 12 characters")
    clear = canonical_json(validate_backup(value)).encode()
    salt, iv = secrets.token_bytes(16), secrets.token_bytes(12)
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600_000, 32)
    return json.dumps(
        {
            "version": 1,
            "kind": "xian-account-backup-encrypted",
            "iterations": 600_000,
            "salt": salt.hex(),
            "iv": iv.hex(),
            "ciphertext": AESGCM(key).encrypt(iv, clear, _AAD).hex(),
        }
    )


def decrypt_backup(text: str, password: str) -> dict:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    if type(text) is not str or len(text) > 100_000:
        raise ValueError("account backup too large")
    v = exact_dict(json.loads(text), {"version", "kind", "iterations", "salt", "iv", "ciphertext"})
    if (
        type(v["version"]) is not int
        or v["version"] != 1
        or v["kind"] != "xian-account-backup-encrypted"
        or type(v["iterations"]) is not int
        or v["iterations"] != 600_000
        or type(v["ciphertext"]) is not str
        or not 32 <= len(v["ciphertext"]) <= 100_000
    ):
        raise ValueError("invalid encrypted account backup")
    salt, iv = hex_bytes(v["salt"], 16), hex_bytes(v["iv"], 12)
    ciphertext = hex_bytes(v["ciphertext"], len(v["ciphertext"]) // 2)
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600_000, 32)
    return validate_backup(json.loads(AESGCM(key).decrypt(iv, ciphertext, _AAD)))


def _sign_secret(keys, epoch, payload, *, ed_seed, pq_secret, role="transaction"):
    if len(pq_secret) == 4032:
        return sign(keys, epoch, payload, ed_seed=ed_seed, pq_secret=pq_secret, role=role)
    from cryptography.hazmat.primitives.asymmetric.mldsa import MLDSA65PrivateKey

    pq = MLDSA65PrivateKey.from_seed_bytes(pq_secret)
    ed = SigningKey(ed_seed)
    if bytes(ed.verify_key) != keys.ed25519 or pq.public_key().public_bytes_raw() != keys.ml_dsa_65:
        raise ValueError("private key mismatch")
    message = signing_transcript(keys, epoch, payload, role=role)
    signature = (
        AUTH_DOMAIN
        + b"\x01\x01"
        + epoch.to_bytes(8, "big")
        + ed.sign(message).signature
        + pq.sign(message)
    )
    if not verify(keys, epoch, payload, signature, role=role):
        raise ValueError("signature self-check failed")
    return signature


def _proof(backup, payload, role):
    record = AccountRecord.from_dict(backup["record"])
    return _sign_secret(
        getattr(record, backup["role"]),
        record.epoch,
        canonical_json(payload).encode(),
        ed_seed=hex_bytes(backup["secret"]["ed25519_seed"], 32),
        pq_secret=hex_bytes(backup["secret"]["ml_dsa_65"], 32 if backup["version"] == 2 else 4032),
        role=role,
    ).hex()


class HybridWallet:
    """Spending wallet retaining the exact legacy identity; never falls back to Ed25519."""

    def __init__(self, backup: dict):
        self._backup = validate_backup(backup)
        if self._backup["role"] != "active":
            raise ValueError("recovery keys cannot spend")

    @property
    def public_key(self):
        return self._backup["sender"]

    def sign_msg(self, _message):
        raise ValueError("legacy message signing is unavailable for hybrid accounts")

    def sign_transaction(self, payload):
        if (
            payload["sender"] != self.public_key
            or payload["chain_id"] != self._backup["chain_id"]
            or payload["contract"] == "_accounts"
        ):
            raise ValueError("account, chain or operation mismatch")
        return {
            "payload": copy.deepcopy(payload),
            "metadata": {
                "tx_format": TX_FORMAT,
                "auth": {
                    "scheme": SCHEME,
                    "signature": _proof(self._backup, payload, "transaction"),
                },
            },
        }


class AccountTransitionDraft:
    """Signing is gated by reopening BOTH encrypted new backup files."""

    def __init__(self, chain_id: str, sender: str, epoch: int):
        active, active_secret = _pair()
        recovery, recovery_secret = _pair()
        record = AccountRecord(epoch, active, recovery).to_dict()
        self.active = validate_backup(
            {
                "version": 1,
                "kind": "xian-account-backup",
                "chain_id": chain_id,
                "sender": sender,
                "record": record,
                "role": "active",
                "secret": active_secret,
            }
        )
        self.recovery = validate_backup(
            {**self.active, "role": "recovery", "secret": recovery_secret}
        )
        self._verified = {}

    def export_backup(self, role: str, password: str) -> str:
        if role not in ("active", "recovery"):
            raise ValueError("invalid backup role")
        return encrypt_backup(getattr(self, role), password)

    def verify_backup(self, role: str, file_contents: str, password: str):
        if role not in ("active", "recovery"):
            raise ValueError("invalid backup role")
        self._verified.pop(role, None)
        value = decrypt_backup(file_contents, password)
        if value != getattr(self, role):
            raise ValueError("not the new backup for this account and role")
        self._verified[role] = canonical_json(value)

    @property
    def ready(self):
        return all(
            self._verified.get(role) == canonical_json(getattr(self, role))
            for role in ("active", "recovery")
        )

    def sign(self, payload: dict, authority: str | dict) -> dict:
        if not self.ready:
            raise ValueError("reopen and verify both new backups first")
        if (
            payload["sender"] != self.active["sender"]
            or payload["chain_id"] != self.active["chain_id"]
            or payload["contract"] != "_accounts"
            or payload["function"] not in ("enroll", "rotate", "recover")
            or payload["kwargs"] != {"record": self.active["record"]}
        ):
            raise ValueError("transition does not match draft")
        if payload["function"] == "enroll":
            key = SigningKey(hex_bytes(authority, 32))
            if (
                bytes(key.verify_key).hex() != payload["sender"].lower()
                or self.active["record"]["epoch"] != 0
            ):
                raise ValueError("invalid enrollment authority")
            signature = key.sign(
                enrollment_transcript(canonical_json(payload).encode())
            ).signature.hex()
        else:
            old = validate_backup(authority)
            role = "recovery" if payload["function"] == "recover" else "active"
            if (
                old["role"] != role
                or old["sender"] != payload["sender"]
                or old["chain_id"] != payload["chain_id"]
                or old["record"]["epoch"] + 1 != self.active["record"]["epoch"]
            ):
                raise ValueError("invalid transition authority")
            signature = _proof(old, payload, "authority")
        return {
            "payload": copy.deepcopy(payload),
            "metadata": {
                "tx_format": TX_FORMAT,
                "auth": {
                    "scheme": ENROLL_SCHEME if payload["function"] == "enroll" else SCHEME,
                    "signature": signature,
                    "active_proof": _proof(self.active, payload, "new_active"),
                    "recovery_proof": _proof(self.recovery, payload, "new_recovery"),
                },
            },
        }
