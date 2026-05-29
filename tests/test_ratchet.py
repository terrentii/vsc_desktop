from mys_crypto import ratchet


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
