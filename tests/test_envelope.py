import pytest

from mys_crypto import envelope, primitives, ratchet, transform


def _pair_with_tkey():
    sk = b"s" * 32
    bob_priv, bob_pub = primitives.generate_x25519_keypair()
    alice = ratchet.ratchet_init_alice(sk, bob_pub)
    bob = ratchet.ratchet_init_bob(sk, (bob_priv, bob_pub))
    tkey = envelope.derive_transform_key(sk)
    return alice, bob, tkey


def test_envelope_round_trip():
    alice, bob, tkey = _pair_with_tkey()
    blob = envelope.seal(alice, tkey, b"hi through envelope")
    assert envelope.open_(bob, tkey, blob) == b"hi through envelope"


def test_envelope_transform_is_outer_layer():
    alice, bob, tkey = _pair_with_tkey()
    blob = envelope.seal(alice, tkey, b"inner check")
    wire = transform.transform_decode(blob, tkey)
    header = ratchet.Header.deserialize(wire[:40])
    ct = wire[40:]
    assert ratchet.ratchet_decrypt(bob, header, ct) == b"inner check"


def test_envelope_rejects_tampered_blob():
    alice, bob, tkey = _pair_with_tkey()
    blob = envelope.seal(alice, tkey, b"intact")
    tampered = blob[:-1] + bytes([blob[-1] ^ 0x01])
    with pytest.raises(Exception):
        envelope.open_(bob, tkey, tampered)
