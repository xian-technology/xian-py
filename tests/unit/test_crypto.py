import pytest

from xian_py.crypto import decrypt_as_receiver, decrypt_as_sender, encrypt
from xian_py.wallet import Wallet


def test_receiver_can_decrypt_encrypted_message() -> None:
    sender = Wallet()
    receiver = Wallet()

    encrypted = encrypt(
        sender.private_key,
        receiver.public_key,
        "xian-secret",
    )

    assert encrypted != "xian-secret"
    assert (
        decrypt_as_receiver(
            sender.public_key,
            receiver.private_key,
            encrypted,
        )
        == "xian-secret"
    )


def test_sender_can_decrypt_reply_from_receiver() -> None:
    sender = Wallet()
    receiver = Wallet()

    encrypted = encrypt(
        receiver.private_key,
        sender.public_key,
        "reply-message",
    )

    assert (
        decrypt_as_sender(
            sender.private_key,
            receiver.public_key,
            encrypted,
        )
        == "reply-message"
    )


def test_encrypt_rejects_invalid_hex_keys() -> None:
    receiver = Wallet()

    with pytest.raises(ValueError):
        encrypt("not-hex", receiver.public_key, "bad-key")
