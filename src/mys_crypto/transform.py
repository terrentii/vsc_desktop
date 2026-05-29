from cryptography.hazmat.primitives.ciphers import Cipher, algorithms

from .primitives import hkdf


def _keystream(key: bytes, length: int) -> bytes:
    if length == 0:
        return b""
    subkey = hkdf(key, 32, salt=b"", info=b"mys-transform-ks-key")
    nonce = bytes(16)
    cipher = Cipher(algorithms.ChaCha20(subkey, nonce), mode=None)
    return cipher.encryptor().update(bytes(length))


def _build_sbox(key: bytes) -> tuple[list[int], list[int]]:
    stream = hkdf(key, 256, salt=b"", info=b"mys-transform-sbox")
    sbox = list(range(256))
    for i in range(255, 0, -1):
        j = stream[255 - i] % (i + 1)
        sbox[i], sbox[j] = sbox[j], sbox[i]
    inv = [0] * 256
    for index, value in enumerate(sbox):
        inv[value] = index
    return sbox, inv


def transform_encode(data: bytes, key: bytes) -> bytes:
    ks = _keystream(key, len(data))
    sbox, _ = _build_sbox(key)
    return bytes(sbox[(b + ks[i]) & 0xFF] for i, b in enumerate(data))


def transform_decode(data: bytes, key: bytes) -> bytes:
    ks = _keystream(key, len(data))
    _, inv = _build_sbox(key)
    return bytes((inv[b] - ks[i]) & 0xFF for i, b in enumerate(data))
