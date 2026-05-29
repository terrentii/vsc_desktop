from .primitives import hkdf
from .ratchet import Header, RatchetState, ratchet_decrypt, ratchet_encrypt
from .transform import transform_decode, transform_encode


def derive_transform_key(sk: bytes) -> bytes:
    return hkdf(sk, 32, salt=b"", info=b"mys-transform-master")


def seal(state: RatchetState, transform_key: bytes, plaintext: bytes, ad: bytes = b"") -> bytes:
    header, ct = ratchet_encrypt(state, plaintext, ad)
    wire = header.serialize() + ct
    return transform_encode(wire, transform_key)


def open_(state: RatchetState, transform_key: bytes, blob: bytes, ad: bytes = b"") -> bytes:
    wire = transform_decode(blob, transform_key)
    header = Header.deserialize(wire[:40])
    ct = wire[40:]
    return ratchet_decrypt(state, header, ct, ad)
