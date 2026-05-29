from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)

_RAW = serialization.Encoding.Raw
_PUB_RAW = serialization.PublicFormat.Raw
_PRIV_RAW = serialization.PrivateFormat.Raw
_NOENC = serialization.NoEncryption()


def generate_x25519_keypair() -> tuple[bytes, bytes]:
    priv = X25519PrivateKey.generate()
    priv_bytes = priv.private_bytes(_RAW, _PRIV_RAW, _NOENC)
    pub_bytes = priv.public_key().public_bytes(_RAW, _PUB_RAW)
    return priv_bytes, pub_bytes


def x25519_shared(private_bytes: bytes, peer_public_bytes: bytes) -> bytes:
    priv = X25519PrivateKey.from_private_bytes(private_bytes)
    peer = X25519PublicKey.from_public_bytes(peer_public_bytes)
    return priv.exchange(peer)
