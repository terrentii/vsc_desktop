from mys_crypto import ratchet
from mys_crypto import primitives


def test_kdf_rk_shapes_and_determinism():
    rk = b"r" * 32
    dh_out = b"d" * 32
    new_rk1, ck1 = ratchet.kdf_rk(rk, dh_out)
    new_rk2, ck2 = ratchet.kdf_rk(rk, dh_out)
    assert (new_rk1, ck1) == (new_rk2, ck2)
    assert len(new_rk1) == 32 and len(ck1) == 32
    assert new_rk1 != rk


def test_kdf_ck_advances():
    ck = b"c" * 32
    new_ck, mk = ratchet.kdf_ck(ck)
    assert len(new_ck) == 32 and len(mk) == 32
    assert new_ck != ck and mk != ck
    assert new_ck != mk


def test_derive_message_keys_shapes():
    key, nonce = ratchet.derive_message_keys(b"m" * 32)
    assert len(key) == 32 and len(nonce) == 12


def test_header_serialize_round_trip():
    dh = b"p" * 32
    h = ratchet.Header(dh=dh, pn=5, n=42)
    blob = h.serialize()
    assert len(blob) == 40
    restored = ratchet.Header.deserialize(blob)
    assert restored.dh == dh
    assert restored.pn == 5
    assert restored.n == 42


def test_ratchet_init_alice_and_bob():
    sk = b"s" * 32
    bob_priv, bob_pub = primitives.generate_x25519_keypair()
    alice = ratchet.ratchet_init_alice(sk, bob_pub)
    bob = ratchet.ratchet_init_bob(sk, (bob_priv, bob_pub))
    assert alice.dhr == bob_pub
    assert alice.cks is not None and alice.ckr is None
    assert bob.dhr is None and bob.rk == sk
    assert bob.cks is None and bob.ckr is None


def _pair():
    sk = b"s" * 32
    bob_priv, bob_pub = primitives.generate_x25519_keypair()
    alice = ratchet.ratchet_init_alice(sk, bob_pub)
    bob = ratchet.ratchet_init_bob(sk, (bob_priv, bob_pub))
    return alice, bob


def test_ratchet_single_message():
    alice, bob = _pair()
    hdr, ct = ratchet.ratchet_encrypt(alice, b"hello bob")
    assert ratchet.ratchet_decrypt(bob, hdr, ct) == b"hello bob"


def test_ratchet_bidirectional_conversation():
    alice, bob = _pair()
    h1, c1 = ratchet.ratchet_encrypt(alice, b"a1")
    assert ratchet.ratchet_decrypt(bob, h1, c1) == b"a1"
    h2, c2 = ratchet.ratchet_encrypt(bob, b"b1")
    assert ratchet.ratchet_decrypt(alice, h2, c2) == b"b1"
    h3, c3 = ratchet.ratchet_encrypt(alice, b"a2")
    assert ratchet.ratchet_decrypt(bob, h3, c3) == b"a2"


def test_ratchet_out_of_order():
    alice, bob = _pair()
    h1, c1 = ratchet.ratchet_encrypt(alice, b"first")
    h2, c2 = ratchet.ratchet_encrypt(alice, b"second")
    assert ratchet.ratchet_decrypt(bob, h2, c2) == b"second"
    assert ratchet.ratchet_decrypt(bob, h1, c1) == b"first"


def test_ratchet_rejects_tampered_ciphertext():
    import pytest
    alice, bob = _pair()
    hdr, ct = ratchet.ratchet_encrypt(alice, b"intact")
    tampered = bytes([ct[0] ^ 0x01]) + ct[1:]
    with pytest.raises(Exception):
        ratchet.ratchet_decrypt(bob, hdr, tampered)
