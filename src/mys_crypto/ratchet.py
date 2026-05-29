import hashlib
import hmac
from dataclasses import dataclass

from .primitives import hkdf


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
