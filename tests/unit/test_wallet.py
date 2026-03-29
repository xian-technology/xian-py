import pytest

import xian_py.wallet as wallet_module
from xian_py.wallet import Wallet, verify_msg


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


def test_hd_wallet_requires_optional_dependency(monkeypatch) -> None:
    monkeypatch.setattr(
        wallet_module,
        "_load_bip_utils",
        lambda: (_ for _ in ()).throw(ImportError("missing bip_utils")),
    )

    with pytest.raises(ImportError, match="missing bip_utils"):
        wallet_module.HDWallet()


def test_ethereum_wallet_requires_optional_dependency(monkeypatch) -> None:
    monkeypatch.setattr(wallet_module, "ETHEREUM_SUPPORT", False)

    with pytest.raises(ImportError, match="xian-tech-py\\[eth\\]"):
        wallet_module.EthereumWallet()
