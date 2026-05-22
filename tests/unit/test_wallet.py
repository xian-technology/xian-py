import hashlib

import pytest

import xian_py.wallet as wallet_module
from xian_py.wallet import Wallet, verify_msg

VALID_MNEMONIC = (
    "abandon abandon abandon abandon abandon abandon abandon abandon "
    "abandon abandon abandon about"
)


class _FakeMnemonic:
    def __init__(self, language: str):
        self.language = language

    def check(self, mnemonic: str) -> bool:
        return self.language == "english" and mnemonic == VALID_MNEMONIC

    @staticmethod
    def to_seed(mnemonic: str) -> bytes:
        assert mnemonic == VALID_MNEMONIC
        return hashlib.pbkdf2_hmac(
            "sha512", mnemonic.encode(), b"mnemonic", 2048, 64
        )


def test_wallet_can_sign_and_verify_messages() -> None:
    wallet = Wallet()
    message = "xian-sdk"

    signature = wallet.sign_msg(message)

    assert wallet.verify_msg(message, signature) is True
    assert verify_msg(wallet.public_key, message, signature) is True
    assert verify_msg(wallet.public_key, "other", signature) is False


def test_wallet_keys_are_valid_hex_strings() -> None:
    wallet = Wallet()

    assert Wallet.is_valid_key(wallet.private_key) is True
    assert Wallet.is_valid_key(wallet.public_key) is True
    assert Wallet.is_valid_key("not-a-key") is False


def test_wallet_reconstructs_from_private_key() -> None:
    wallet = Wallet()
    restored = Wallet(wallet.private_key)
    message = "restore-check"

    assert restored.private_key == wallet.private_key
    assert restored.public_key == wallet.public_key
    assert wallet.verify_msg(message, restored.sign_msg(message)) is True


def test_wallet_derives_browser_mobile_xian_v1_mnemonic(monkeypatch) -> None:
    monkeypatch.setattr(wallet_module, "_load_mnemonic_library", lambda: _FakeMnemonic)

    wallet = Wallet.from_mnemonic_xian_v1(VALID_MNEMONIC.upper())
    second_wallet = Wallet.from_mnemonic_xian_v1(VALID_MNEMONIC, account_index=1)

    assert (
        wallet.private_key
        == "457c57823c3ba5c795eb91a34b3a666d2bdf7a40bf8154e715dcf687a3ded6ec"
    )
    assert (
        second_wallet.private_key
        == "a40393033de03256f7d4b2c42860464879c6d763febbc89a25989598af246fa7"
    )
    assert wallet.public_key != second_wallet.public_key


def test_wallet_rejects_invalid_xian_v1_mnemonic_index(monkeypatch) -> None:
    monkeypatch.setattr(wallet_module, "_load_mnemonic_library", lambda: _FakeMnemonic)

    with pytest.raises(ValueError, match="account_index"):
        Wallet.from_mnemonic_xian_v1(VALID_MNEMONIC, account_index=-1)
    with pytest.raises(ValueError, match="account_index"):
        Wallet.from_mnemonic_xian_v1(VALID_MNEMONIC, account_index=True)


def test_ethereum_address_validation_accepts_prefixed_and_plain_hex() -> None:
    assert wallet_module.EthereumWallet.is_valid_key("0x" + "a" * 40) is True
    assert wallet_module.EthereumWallet.is_valid_key("b" * 40) is True
    assert wallet_module.EthereumWallet.is_valid_key("0x" + "g" * 40) is False
    assert wallet_module.EthereumWallet.is_valid_key("0x" + "a" * 39) is False


def test_hd_wallet_requires_optional_dependency(monkeypatch) -> None:
    monkeypatch.setattr(
        wallet_module,
        "_load_mnemonic_library",
        lambda: (_ for _ in ()).throw(ImportError("missing mnemonic")),
    )

    with pytest.raises(ImportError, match="missing mnemonic"):
        wallet_module.HDWallet()


def test_ethereum_wallet_requires_optional_dependency(monkeypatch) -> None:
    monkeypatch.setattr(wallet_module, "ETHEREUM_SUPPORT", False)

    with pytest.raises(ImportError, match="xian-tech-py\\[eth\\]"):
        wallet_module.EthereumWallet()
