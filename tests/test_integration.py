from mys_crypto import envelope, primitives, ratchet


def _session():
    sk = b"z" * 32
    bob_priv, bob_pub = primitives.generate_x25519_keypair()
    alice = ratchet.ratchet_init_alice(sk, bob_pub)
    bob = ratchet.ratchet_init_bob(sk, (bob_priv, bob_pub))
    tkey = envelope.derive_transform_key(sk)
    return alice, bob, tkey


def test_full_bidirectional_conversation():
    alice, bob, tkey = _session()
    for i in range(3):
        blob = envelope.seal(alice, tkey, f"a{i}".encode())
        assert envelope.open_(bob, tkey, blob) == f"a{i}".encode()
    blob = envelope.seal(bob, tkey, b"reply")
    assert envelope.open_(alice, tkey, blob) == b"reply"
    blob = envelope.seal(alice, tkey, b"after ratchet")
    assert envelope.open_(bob, tkey, blob) == b"after ratchet"


def test_out_of_order_delivery_through_envelope():
    alice, bob, tkey = _session()
    blob1 = envelope.seal(alice, tkey, b"msg-1")
    blob2 = envelope.seal(alice, tkey, b"msg-2")
    blob3 = envelope.seal(alice, tkey, b"msg-3")
    assert envelope.open_(bob, tkey, blob3) == b"msg-3"
    assert envelope.open_(bob, tkey, blob1) == b"msg-1"
    assert envelope.open_(bob, tkey, blob2) == b"msg-2"
