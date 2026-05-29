from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from argon2.low_level import Type, hash_secret_raw
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
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


def generate_ed25519_keypair() -> tuple[bytes, bytes]:
    priv = Ed25519PrivateKey.generate()
    priv_bytes = priv.private_bytes(_RAW, _PRIV_RAW, _NOENC)
    pub_bytes = priv.public_key().public_bytes(_RAW, _PUB_RAW)
    return priv_bytes, pub_bytes


def ed25519_sign(private_bytes: bytes, message: bytes) -> bytes:
    priv = Ed25519PrivateKey.from_private_bytes(private_bytes)
    return priv.sign(message)


def aead_encrypt(key: bytes, nonce: bytes, plaintext: bytes, aad: bytes) -> bytes:
    return ChaCha20Poly1305(key).encrypt(nonce, plaintext, aad)


def aead_decrypt(key: bytes, nonce: bytes, ciphertext: bytes, aad: bytes) -> bytes:
    return ChaCha20Poly1305(key).decrypt(nonce, ciphertext, aad)


def hkdf(ikm: bytes, length: int, salt: bytes, info: bytes) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(),
        length=length,
        salt=salt,
        info=info,
    ).derive(ikm)


def argon2id(
    password: bytes,
    salt: bytes,
    length: int,
    time_cost: int = 3,
    memory_cost: int = 65536,
    parallelism: int = 4,
) -> bytes:
    return hash_secret_raw(
        secret=password,
        salt=salt,
        time_cost=time_cost,
        memory_cost=memory_cost,
        parallelism=parallelism,
        hash_len=length,
        type=Type.ID,
    )


def ed25519_verify(public_bytes: bytes, signature: bytes, message: bytes) -> bool:
    pub = Ed25519PublicKey.from_public_bytes(public_bytes)
    try:
        pub.verify(signature, message)
        return True
    except InvalidSignature:
        return False
