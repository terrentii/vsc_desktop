from mys_crypto import envelope, primitives, ratchet


def _pair():
    sk = b"s" * 32
    bob_priv, bob_pub = primitives.generate_x25519_keypair()
    alice = ratchet.ratchet_init_alice(sk, bob_pub)
    bob = ratchet.ratchet_init_bob(sk, (bob_priv, bob_pub))
    return alice, bob, envelope.derive_transform_key(sk)


def test_serialize_round_trip_preserves_fields():
    alice, _, _ = _pair()
    blob = ratchet.serialize_state(alice)
    restored = ratchet.deserialize_state(blob)
    assert restored.dhs == alice.dhs
    assert restored.dhr == alice.dhr
    assert restored.rk == alice.rk
    assert restored.cks == alice.cks
    assert restored.ckr == alice.ckr
    assert (restored.ns, restored.nr, restored.pn) == (alice.ns, alice.nr, alice.pn)


def test_serialized_state_continues_conversation():
    alice, bob, tkey = _pair()
    # один обмен, затем сериализуем обе стороны и продолжаем из восстановленных
    blob = envelope.seal(alice, tkey, b"first")
    assert envelope.open_(bob, tkey, blob) == b"first"
    alice = ratchet.deserialize_state(ratchet.serialize_state(alice))
    bob = ratchet.deserialize_state(ratchet.serialize_state(bob))
    # ответ Боба -> DH-ratchet у Алисы
    blob = envelope.seal(bob, tkey, b"reply")
    assert envelope.open_(alice, tkey, blob) == b"reply"
    blob = envelope.seal(alice, tkey, b"third")
    assert envelope.open_(bob, tkey, blob) == b"third"


def test_serialized_state_preserves_skipped_keys():
    alice, bob, tkey = _pair()
    b1 = envelope.seal(alice, tkey, b"m1")
    b2 = envelope.seal(alice, tkey, b"m2")
    # доставляем m2 первым -> у Боба появляется пропущенный ключ для m1
    assert envelope.open_(bob, tkey, b2) == b"m2"
    bob = ratchet.deserialize_state(ratchet.serialize_state(bob))
    assert len(bob.mkskipped) == 1
    assert envelope.open_(bob, tkey, b1) == b"m1"


def test_global_skip_cap_evicts_oldest(monkeypatch):
    monkeypatch.setattr(ratchet, "MAX_SKIP_SESSION", 5)
    alice, bob, tkey = _pair()
    blobs = [envelope.seal(alice, tkey, f"m{i}".encode()) for i in range(8)]
    # доставляем последнее -> Боб пропускает ключи m0..m6 (7 шт.), кап = 5
    assert envelope.open_(bob, tkey, blobs[7]) == b"m7"
    assert len(bob.mkskipped) == 5
    # старейшие (m0, m1) вытеснены -> не расшифровать
    import pytest
    with pytest.raises(Exception):
        envelope.open_(bob, tkey, blobs[0])
    # сохранившиеся (например m6) -> расшифровываются
    assert envelope.open_(bob, tkey, blobs[6]) == b"m6"
