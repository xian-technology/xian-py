import secrets
from functools import lru_cache

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
            "group; install with 'pip install xian-py[eth]'"
        )


@lru_cache(maxsize=1)
def _load_bip_utils() -> dict[str, object]:
    try:
        from bip_utils import (
            Bip32Secp256k1,
            Bip32Slip10Ed25519,
            Bip39MnemonicGenerator,
            Bip39SeedGenerator,
            Bip39WordsNum,
            Bip44,
            Bip44Changes,
            Bip44Coins,
        )
        from bip_utils.utils.mnemonic import Mnemonic
    except ImportError as exc:
        raise ImportError(
            "HD wallet support requires the optional 'hd' dependency group; "
            "install with 'pip install xian-py[hd]'"
        ) from exc

    return {
        "Bip32Secp256k1": Bip32Secp256k1,
        "Bip32Slip10Ed25519": Bip32Slip10Ed25519,
        "Bip39MnemonicGenerator": Bip39MnemonicGenerator,
        "Bip39SeedGenerator": Bip39SeedGenerator,
        "Bip39WordsNum": Bip39WordsNum,
        "Bip44": Bip44,
        "Bip44Changes": Bip44Changes,
        "Bip44Coins": Bip44Coins,
        "Mnemonic": Mnemonic,
    }


# TODO: Unify this function with the method with the same name from 'Wallet' class
def verify_msg(public_key: str, msg: str, signature: str) -> bool:
    """Verify signed message by public key."""
    return verify_message(public_key, msg, signature)


class Wallet:
    def __init__(self, private_key: str = None):
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
        return self._account.verify_message(msg, signature)

    @staticmethod
    def is_valid_key(key: str) -> bool:
        """Check if the given key (public or private) is valid."""
        return is_valid_ed25519_key(key)


class EthereumWallet:
    def __init__(self, private_key: str = None):
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
        except Exception:
            return False

    @staticmethod
    def is_valid_key(key: str) -> bool:
        """Check if the given key is a valid Ethereum address"""
        try:
            # Ethereum addresses are 40 hex chars (not counting '0x')
            if key.startswith("0x"):
                key = key[2:]
            if len(key) != 40:
                return False
            int(key, 16)
            return True
        except Exception:
            return False


class HDWallet:
    def __init__(self, mnemonic: str = None):
        bip_utils = _load_bip_utils()
        mnemonic_type = bip_utils["Mnemonic"]
        words_num = bip_utils["Bip39WordsNum"]
        mnemonic_generator = bip_utils["Bip39MnemonicGenerator"]
        seed_generator = bip_utils["Bip39SeedGenerator"]
        ed25519_key = bip_utils["Bip32Slip10Ed25519"]
        secp256k1_key = bip_utils["Bip32Secp256k1"]

        if mnemonic:
            self.mnemonic = mnemonic_type(mnemonic.split())
        else:
            self.mnemonic = mnemonic_generator().FromWordsNumber(
                words_num.WORDS_NUM_24
            )

        self.seed_bytes = seed_generator(self.mnemonic).Generate()

        # Initialize ED25519 master key
        self.ed25519_master_key = ed25519_key.FromSeed(self.seed_bytes)

        # Only initialize secp256k1 if ethereum support is installed
        if ETHEREUM_SUPPORT:
            self.secp256k1_master_key = secp256k1_key.FromSeed(self.seed_bytes)

    @property
    def mnemonic_str(self) -> str:
        """Returns the mnemonic seed as a string"""
        return str(self.mnemonic)

    @property
    def mnemonic_lst(self) -> list[str]:
        """Returns the mnemonic seed as a list of strings"""
        return str(self.mnemonic).split()

    def get_wallet(self, derivation_path):
        """Get ED25519 wallet for custom derivation path"""
        child_key = self.ed25519_master_key
        for index in derivation_path:
            # Automatically harden the index
            hardened_index = index + 0x80000000
            child_key = child_key.ChildKey(hardened_index)
        private_key_hex = child_key.PrivateKey().Raw().ToHex()
        return Wallet(private_key=private_key_hex)

    def get_ethereum_wallet(self, account_idx: int = 0):
        """Get Ethereum wallet for specific account index"""
        if not ETHEREUM_SUPPORT:
            raise ImportError(
                "Ethereum support not installed. Install with 'pip install xian-py[eth]'"
            )

        bip_utils = _load_bip_utils()
        bip44 = bip_utils["Bip44"]
        bip44_changes = bip_utils["Bip44Changes"]
        bip44_coins = bip_utils["Bip44Coins"]
        bip44_ctx = bip44.FromSeed(self.seed_bytes, bip44_coins.ETHEREUM)
        account_keys = (
            bip44_ctx.Purpose()
            .Coin()
            .Account(0)
            .Change(bip44_changes.CHAIN_EXT)
        )
        eth_child_key = account_keys.AddressIndex(account_idx)
        private_key_hex = eth_child_key.PrivateKey().Raw().ToHex()
        return EthereumWallet(private_key=private_key_hex)
