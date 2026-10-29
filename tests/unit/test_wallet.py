import hashlib

import pytest

import xian_py.wallet as wallet_module
from xian_py.wallet import Wallet, verify_msg

VALID_MNEMONIC = (
    "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
)


class _FakeMnemonic:
    def __init__(self, language: str):
        self.language = language

    def check(self, mnemonic: str) -> bool:
        return self.language == "english" and mnemonic == VALID_MNEMONIC

    def generate(self, strength: int) -> str:
        assert strength == 256
        return VALID_MNEMONIC

    @staticmethod
    def to_seed(mnemonic: str) -> bytes:
        assert mnemonic == VALID_MNEMONIC
        return hashlib.pbkdf2_hmac("sha512", mnemonic.encode(), b"mnemonic", 2048, 64)


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


def test_wallet_derives_browser_mobile_xian_mnemonic(monkeypatch) -> None:
    monkeypatch.setattr(wallet_module, "_load_mnemonic_library", lambda: _FakeMnemonic)

    wallet = Wallet.from_mnemonic(VALID_MNEMONIC.upper())
    second_wallet = Wallet.from_mnemonic(VALID_MNEMONIC, account_index=1)

    assert wallet.private_key == "b3aee0ed179a18a754136d3d134c03e9c1ad97eb2e9912401dc2d9ffc96882e0"
    assert (
        second_wallet.private_key
        == "f1f4674448f4d17a78af6b150a7fa45a752d0014fb0235604a339a898695ce69"
    )
    assert wallet.public_key != second_wallet.public_key


def test_wallet_rejects_invalid_xian_mnemonic_index(monkeypatch) -> None:
    monkeypatch.setattr(wallet_module, "_load_mnemonic_library", lambda: _FakeMnemonic)

    with pytest.raises(ValueError, match="account_index"):
        Wallet.from_mnemonic(VALID_MNEMONIC, account_index=-1)
    with pytest.raises(ValueError, match="account_index"):
        Wallet.from_mnemonic(VALID_MNEMONIC, account_index=True)


@pytest.mark.parametrize(
    ("account_index", "expected_private_key"),
    [
        (0, "b3aee0ed179a18a754136d3d134c03e9c1ad97eb2e9912401dc2d9ffc96882e0"),
        (1, "f1f4674448f4d17a78af6b150a7fa45a752d0014fb0235604a339a898695ce69"),
    ],
)
def test_hd_wallet_matches_browser_mobile_accounts(
    monkeypatch, account_index, expected_private_key
) -> None:
    monkeypatch.setattr(wallet_module, "_load_mnemonic_library", lambda: _FakeMnemonic)

    restored = wallet_module.HDWallet(VALID_MNEMONIC).get_wallet(account_index=account_index)
    indexed = Wallet.from_mnemonic(VALID_MNEMONIC, account_index=account_index)

    assert restored.private_key == indexed.private_key == expected_private_key
    assert restored.public_key == indexed.public_key
    assert indexed.verify_msg("indexed-recovery", restored.sign_msg("indexed-recovery"))


def test_hd_wallet_defaults_to_first_browser_mobile_account(monkeypatch) -> None:
    monkeypatch.setattr(wallet_module, "_load_mnemonic_library", lambda: _FakeMnemonic)

    restored = wallet_module.HDWallet(VALID_MNEMONIC).get_wallet()

    assert restored.public_key == "7e15e2e068cb41b5c4b51dafef23d944aa7d120d362097d1f7c02100da5c2be5"


def test_generated_hd_wallet_can_be_restored_with_wallet(monkeypatch) -> None:
    monkeypatch.setattr(wallet_module, "_load_mnemonic_library", lambda: _FakeMnemonic)

    hd = wallet_module.HDWallet()

    assert hd.get_wallet().public_key == Wallet.from_mnemonic(hd.mnemonic_str).public_key
    assert (
        hd.get_wallet(0xFFFFFFFF).public_key
        == Wallet.from_mnemonic(hd.mnemonic_str, 0xFFFFFFFF).public_key
    )


def test_hd_wallet_normalizes_recovery_phrase_like_wallet(monkeypatch) -> None:
    monkeypatch.setattr(wallet_module, "_load_mnemonic_library", lambda: _FakeMnemonic)
    phrase = "  " + VALID_MNEMONIC.upper().replace(" ", " \n ") + "  "

    hd = wallet_module.HDWallet(phrase)

    assert hd.mnemonic_str == VALID_MNEMONIC
    assert hd.mnemonic_lst == VALID_MNEMONIC.split()
    assert hd.get_wallet(1).public_key == Wallet.from_mnemonic(phrase, 1).public_key


@pytest.mark.parametrize("phrase", ["", "   ", "not a recovery phrase", "abandon " * 12])
def test_hd_wallet_rejects_invalid_supplied_phrase(monkeypatch, phrase) -> None:
    monkeypatch.setattr(wallet_module, "_load_mnemonic_library", lambda: _FakeMnemonic)

    with pytest.raises(ValueError, match="invalid BIP39 mnemonic"):
        wallet_module.HDWallet(phrase)


@pytest.mark.parametrize("index", [-1, 0x100000000, True, 1.0, "1", None, [44, 734, 0, 0, 0]])
def test_hd_wallet_rejects_invalid_account_index_and_obsolete_paths(monkeypatch, index) -> None:
    monkeypatch.setattr(wallet_module, "_load_mnemonic_library", lambda: _FakeMnemonic)
    hd = wallet_module.HDWallet(VALID_MNEMONIC)

    with pytest.raises(ValueError, match="account_index"):
        hd.get_wallet(index)


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
