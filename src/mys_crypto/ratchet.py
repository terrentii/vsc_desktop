import hashlib
import hmac
from dataclasses import dataclass

from .primitives import hkdf, generate_x25519_keypair, x25519_shared


@dataclass
class Header:
    dh: bytes
    pn: int
    n: int

    def serialize(self) -> bytes:
        return self.dh + self.pn.to_bytes(4, "big") + self.n.to_bytes(4, "big")

    @classmethod
    def deserialize(cls, blob: bytes) -> "Header":
        return cls(
            dh=blob[:32],
            pn=int.from_bytes(blob[32:36], "big"),
            n=int.from_bytes(blob[36:40], "big"),
        )


def kdf_rk(rk: bytes, dh_out: bytes) -> tuple[bytes, bytes]:
    out = hkdf(dh_out, 64, salt=rk, info=b"mys-ratchet-rk")
    return out[:32], out[32:]


def kdf_ck(ck: bytes) -> tuple[bytes, bytes]:
    mk = hmac.new(ck, b"\x01", hashlib.sha256).digest()
    new_ck = hmac.new(ck, b"\x02", hashlib.sha256).digest()
    return new_ck, mk


def derive_message_keys(mk: bytes) -> tuple[bytes, bytes]:
    out = hkdf(mk, 44, salt=bytes(32), info=b"mys-ratchet-msg")
    return out[:32], out[32:44]


@dataclass
class RatchetState:
    dhs: tuple[bytes, bytes]
    dhr: bytes | None
    rk: bytes
    cks: bytes | None
    ckr: bytes | None
    ns: int
    nr: int
    pn: int
    mkskipped: dict[tuple[bytes, int], bytes]


def ratchet_init_alice(sk: bytes, bob_dh_pub: bytes) -> RatchetState:
    dhs = generate_x25519_keypair()
    rk, cks = kdf_rk(sk, x25519_shared(dhs[0], bob_dh_pub))
    return RatchetState(
        dhs=dhs, dhr=bob_dh_pub, rk=rk, cks=cks, ckr=None,
        ns=0, nr=0, pn=0, mkskipped={},
    )


def ratchet_init_bob(sk: bytes, bob_dh_keypair: tuple[bytes, bytes]) -> RatchetState:
    return RatchetState(
        dhs=bob_dh_keypair, dhr=None, rk=sk, cks=None, ckr=None,
        ns=0, nr=0, pn=0, mkskipped={},
    )
