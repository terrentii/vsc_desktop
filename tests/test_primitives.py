import pytest

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


def test_aead_round_trip():
    key = b"k" * 32
    nonce = b"n" * 12
    pt = b"secret payload"
    aad = b"header"
    ct = primitives.aead_encrypt(key, nonce, pt, aad)
    assert ct != pt
    assert primitives.aead_decrypt(key, nonce, ct, aad) == pt


def test_aead_rejects_wrong_aad():
    key = b"k" * 32
    nonce = b"n" * 12
    ct = primitives.aead_encrypt(key, nonce, b"data", b"aad1")
    with pytest.raises(Exception):
        primitives.aead_decrypt(key, nonce, ct, b"aad2")


def test_hkdf_deterministic_and_length():
    ikm = b"input key material"
    out1 = primitives.hkdf(ikm, 64, salt=b"salt", info=b"info")
    out2 = primitives.hkdf(ikm, 64, salt=b"salt", info=b"info")
    assert out1 == out2
    assert len(out1) == 64
    out3 = primitives.hkdf(ikm, 64, salt=b"salt", info=b"other")
    assert out3 != out1


def test_argon2id_deterministic_and_salt_sensitive():
    h1 = primitives.argon2id(b"password", b"saltsaltsaltsalt", 32)
    h2 = primitives.argon2id(b"password", b"saltsaltsaltsalt", 32)
    h3 = primitives.argon2id(b"password", b"DIFFERENTsaltxxx", 32)
    assert h1 == h2
    assert len(h1) == 32
    assert h1 != h3
