from nacl.bindings import (
    crypto_sign_ed25519_pk_to_curve25519,
    crypto_sign_ed25519_sk_to_curve25519,
)
from nacl.public import Box, PrivateKey, PublicKey
from nacl.signing import SigningKey


def _private_key_from_ed25519_hex(private_key: str) -> PrivateKey:
    ed25519_seed = bytes.fromhex(private_key)
    signing_key = SigningKey(ed25519_seed)
    full_ed25519_sk = ed25519_seed + signing_key.verify_key.encode()
    return PrivateKey(crypto_sign_ed25519_sk_to_curve25519(full_ed25519_sk))


def _public_key_from_ed25519_hex(public_key: str) -> PublicKey:
    return PublicKey(crypto_sign_ed25519_pk_to_curve25519(bytes.fromhex(public_key)))


def encrypt(
    sender_private_key: str, receiver_public_key: str, cleartext_msg: str
) -> str:
    """
    Encrypts a message using the sender's private key and the receiver's public key.

    This function creates a mutual-authentication encryption scheme where the sender's
    identity is authenticated via their private key, and the message is encrypted
    such that only the intended receiver with the corresponding private key can decrypt it.

    Args:
        sender_private_key (str): The sender's Ed25519 private key in hexadecimal format.
        receiver_public_key (str): The receiver's Ed25519 public key in hexadecimal format.
        cleartext_msg (str): The plaintext message to encrypt.

    Returns:
        str: The encrypted message as a hexadecimal string.
    """
    sender_pk = _private_key_from_ed25519_hex(sender_private_key)
    recipient_pk = _public_key_from_ed25519_hex(receiver_public_key)

    box = Box(sender_pk, recipient_pk)
    encrypted = box.encrypt(cleartext_msg.encode("utf-8"))
    return encrypted.hex()


def decrypt_as_receiver(
    sender_public_key: str, receiver_private_key: str, encrypted_msg: str
) -> str:
    """
    Decrypts a message as the intended receiver using the receiver's private key and sender's public key.

    This function assumes that the message was encrypted using the sender's private key
    and the receiver's public key in a mutual-authentication encryption scheme.

    Args:
        sender_public_key (str): The sender's Ed25519 public key in hexadecimal format.
        receiver_private_key (str): The receiver's Ed25519 private key in hexadecimal format.
        encrypted_msg (str): The encrypted message as a hexadecimal string.

    Returns:
        str: The decrypted plaintext message.
    """
    recipient_sk = _private_key_from_ed25519_hex(receiver_private_key)
    sender_pk = _public_key_from_ed25519_hex(sender_public_key)

    recipient_box = Box(recipient_sk, sender_pk)
    decrypted_plaintext = recipient_box.decrypt(bytes.fromhex(encrypted_msg))
    return decrypted_plaintext.decode("utf-8")


def decrypt_as_sender(
    sender_private_key: str, receiver_public_key: str, encrypted_msg: str
) -> str:
    """
    Decrypts a message as the sender using the sender's private key and the receiver's public key.

    This function assumes that the message was encrypted using the receiver's private key
    and the sender's public key, allowing the sender to decrypt it.

    Args:
        sender_private_key (str): The sender's Ed25519 private key in hexadecimal format.
        receiver_public_key (str): The receiver's Ed25519 public key in hexadecimal format.
        encrypted_msg (str): The encrypted message as a hexadecimal string.

    Returns:
        str: The decrypted plaintext message.
    """
    sender_sk = _private_key_from_ed25519_hex(sender_private_key)
    receiver_pk = _public_key_from_ed25519_hex(receiver_public_key)

    sender_box = Box(sender_sk, receiver_pk)
    decrypted_plaintext = sender_box.decrypt(bytes.fromhex(encrypted_msg))
    return decrypted_plaintext.decode("utf-8")
