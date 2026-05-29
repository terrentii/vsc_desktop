from mys_crypto import primitives


def test_x25519_shared_secret_agreement():
    a_priv, a_pub = primitives.generate_x25519_keypair()
    b_priv, b_pub = primitives.generate_x25519_keypair()
    assert len(a_pub) == 32 and len(a_priv) == 32
    secret_a = primitives.x25519_shared(a_priv, b_pub)
    secret_b = primitives.x25519_shared(b_priv, a_pub)
    assert secret_a == secret_b
    assert len(secret_a) == 32


def test_x25519_keys_are_random():
    _, pub1 = primitives.generate_x25519_keypair()
    _, pub2 = primitives.generate_x25519_keypair()
    assert pub1 != pub2


def test_ed25519_sign_verify():
    priv, pub = primitives.generate_ed25519_keypair()
    msg = b"mys message"
    sig = primitives.ed25519_sign(priv, msg)
    assert primitives.ed25519_verify(pub, sig, msg) is True


def test_ed25519_rejects_tampered_message():
    priv, pub = primitives.generate_ed25519_keypair()
    sig = primitives.ed25519_sign(priv, b"original")
    assert primitives.ed25519_verify(pub, sig, b"tampered") is False
