import hashlib
import hmac
import secrets
from functools import lru_cache
from typing import TypeAlias

from xian_accounts import (
    Ed25519Account,
    is_valid_ed25519_key,
    verify_message,
)

try:
    from eth_account import Account
    from eth_account.messages import encode_defunct

    ETHEREUM_SUPPORT = True
except ImportError:
    ETHEREUM_SUPPORT = False


def _require_ethereum_support() -> None:
    if not ETHEREUM_SUPPORT:
        raise ImportError(
            "Ethereum wallet helpers require the optional 'eth' dependency "
            "group; install with 'uv add \"xian-tech-py[eth]\"'"
        )


@lru_cache(maxsize=1)
def _load_mnemonic_library():
    try:
        from mnemonic import Mnemonic
    except ImportError as exc:
        raise ImportError(
            "HD wallet support requires the optional 'hd' dependency group; "
            "install with 'uv add \"xian-tech-py[hd]\"'"
        ) from exc
    return Mnemonic


def _derive_slip10_ed25519_private_key(
    seed: bytes, derivation_path: list[int]
) -> str:
    digest = hmac.new(b"ed25519 seed", seed, hashlib.sha512).digest()
    private_key = digest[:32]
    chain_code = digest[32:]

    for index in derivation_path:
        hardened_index = index + 0x80000000
        data = b"\x00" + private_key + hardened_index.to_bytes(4, "big")
        digest = hmac.new(chain_code, data, hashlib.sha512).digest()
        private_key = digest[:32]
        chain_code = digest[32:]

    return private_key.hex()


WalletPrivateKey: TypeAlias = str | None


def _verify_ed25519_message(public_key: str, msg: str, signature: str) -> bool:
    return verify_message(public_key, msg, signature)


def verify_msg(public_key: str, msg: str, signature: str) -> bool:
    """Verify signed message by public key."""
    return _verify_ed25519_message(public_key, msg, signature)


class Wallet:
    def __init__(self, private_key: WalletPrivateKey = None):
        if private_key:
            self._account = Ed25519Account(private_key)
        else:
            self._account = Ed25519Account.generate()

    @property
    def private_key(self) -> str:
        return self._account.private_key

    @property
    def public_key(self) -> str:
        return self._account.public_key

    def sign_msg(self, msg: str):
        """Sign message with private key."""
        return self._account.sign_message(msg)

    def verify_msg(self, msg: str, signature: str) -> bool:
        """Verify signed message."""
        return _verify_ed25519_message(self.public_key, msg, signature)

    @staticmethod
    def is_valid_key(key: str) -> bool:
        """Check if the given key (public or private) is valid."""
        return is_valid_ed25519_key(key)


class EthereumWallet:
    def __init__(self, private_key: WalletPrivateKey = None):
        _require_ethereum_support()
        if private_key:
            private_key = bytes.fromhex(private_key)
        else:
            private_key = secrets.token_bytes(32)

        self.account = Account.from_key(private_key)

    @property
    def private_key(self) -> str:
        return str(self.account.key.hex())

    @property
    def address(self) -> str:
        return str(self.account.address)

    # Compatibility alias for older code paths that treated the Ethereum
    # address as the account identifier.
    @property
    def public_key(self) -> str:
        return self.address

    def sign_msg(self, msg: str):
        """Sign message with private key"""
        message = encode_defunct(text=msg)
        signed_message = self.account.sign_message(message)
        return signed_message.signature.hex()

    def verify_msg(self, msg: str, signature: str) -> bool:
        """Verify signed message"""
        message = encode_defunct(text=msg)
        try:
            recovered_address = Account.recover_message(
                message, signature=bytes.fromhex(signature)
            )
            return recovered_address.lower() == self.address.lower()
        except (TypeError, ValueError):
            return False

    @staticmethod
    def is_valid_key(key: str) -> bool:
        """Check if the given key is a valid Ethereum address"""
        if not isinstance(key, str):
            return False
        normalized = key[2:] if key.startswith("0x") else key
        if len(normalized) != 40:
            return False
        try:
            int(normalized, 16)
        except ValueError:
            return False
        return True


class HDWallet:
    def __init__(self, mnemonic: str | None = None):
        mnemonic_type = _load_mnemonic_library()
        mnemonic_library = mnemonic_type("english")

        if mnemonic:
            if not mnemonic_library.check(mnemonic):
                raise ValueError("invalid BIP39 mnemonic")
            self.mnemonic = mnemonic
        else:
            self.mnemonic = mnemonic_library.generate(strength=256)

        self.seed_bytes = mnemonic_type.to_seed(self.mnemonic)

    @property
    def mnemonic_str(self) -> str:
        """Returns the mnemonic seed as a string"""
        return self.mnemonic

    @property
    def mnemonic_lst(self) -> list[str]:
        """Returns the mnemonic seed as a list of strings"""
        return self.mnemonic.split()

    def get_wallet(self, derivation_path):
        """Get ED25519 wallet for custom derivation path"""
        private_key_hex = _derive_slip10_ed25519_private_key(
            self.seed_bytes, derivation_path
        )
        return Wallet(private_key=private_key_hex)

    def get_ethereum_wallet(self, account_idx: int = 0):
        """Get Ethereum wallet for specific account index"""
        _require_ethereum_support()
        Account.enable_unaudited_hdwallet_features()
        account = Account.from_mnemonic(
            self.mnemonic,
            account_path=f"m/44'/60'/0'/0/{account_idx}",
        )
        private_key_hex = account.key.hex()
        return EthereumWallet(private_key=private_key_hex)
