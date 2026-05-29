import copy
import hashlib
import hmac
from dataclasses import dataclass

from .primitives import hkdf, generate_x25519_keypair, x25519_shared, aead_encrypt, aead_decrypt


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


MAX_SKIP = 1000


def ratchet_encrypt(state: RatchetState, plaintext: bytes, ad: bytes = b"") -> tuple[Header, bytes]:
    state.cks, mk = kdf_ck(state.cks)
    header = Header(dh=state.dhs[1], pn=state.pn, n=state.ns)
    state.ns += 1
    key, nonce = derive_message_keys(mk)
    ct = aead_encrypt(key, nonce, plaintext, ad + header.serialize())
    return header, ct


def ratchet_decrypt(state: RatchetState, header: Header, ciphertext: bytes, ad: bytes = b"") -> bytes:
    work = copy.deepcopy(state)
    plaintext = _ratchet_decrypt_into(work, header, ciphertext, ad)
    _commit(state, work)
    return plaintext


def _ratchet_decrypt_into(state: RatchetState, header: Header, ciphertext: bytes, ad: bytes) -> bytes:
    skipped = _try_skipped(state, header, ciphertext, ad)
    if skipped is not None:
        return skipped
    if header.dh != state.dhr:
        _skip_message_keys(state, header.pn)
        _dh_ratchet(state, header)
    _skip_message_keys(state, header.n)
    state.ckr, mk = kdf_ck(state.ckr)
    state.nr += 1
    key, nonce = derive_message_keys(mk)
    return aead_decrypt(key, nonce, ciphertext, ad + header.serialize())


def _commit(state: RatchetState, work: RatchetState) -> None:
    state.dhs = work.dhs
    state.dhr = work.dhr
    state.rk = work.rk
    state.cks = work.cks
    state.ckr = work.ckr
    state.ns = work.ns
    state.nr = work.nr
    state.pn = work.pn
    state.mkskipped = work.mkskipped


def _try_skipped(state: RatchetState, header: Header, ciphertext: bytes, ad: bytes) -> bytes | None:
    key_id = (header.dh, header.n)
    if key_id not in state.mkskipped:
        return None
    mk = state.mkskipped.pop(key_id)
    key, nonce = derive_message_keys(mk)
    return aead_decrypt(key, nonce, ciphertext, ad + header.serialize())


def _skip_message_keys(state: RatchetState, until: int) -> None:
    if state.ckr is None:
        return
    if state.nr + MAX_SKIP < until:
        raise ValueError("too many skipped messages")
    while state.nr < until:
        state.ckr, mk = kdf_ck(state.ckr)
        state.mkskipped[(state.dhr, state.nr)] = mk
        state.nr += 1


def _dh_ratchet(state: RatchetState, header: Header) -> None:
    state.pn = state.ns
    state.ns = 0
    state.nr = 0
    state.dhr = header.dh
    state.rk, state.ckr = kdf_rk(state.rk, x25519_shared(state.dhs[0], state.dhr))
    state.dhs = generate_x25519_keypair()
    state.rk, state.cks = kdf_rk(state.rk, x25519_shared(state.dhs[0], state.dhr))
