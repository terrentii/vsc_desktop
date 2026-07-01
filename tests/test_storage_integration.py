from mys_crypto import envelope, primitives, ratchet
from mys_storage import create_vault, open_vault

FAST = {"time_cost": 1, "memory_cost": 8, "parallelism": 1}


def test_full_conversation_persisted_across_reload(tmp_path):
    """Два устройства: состояние ratchet каждый шаг грузится из БД (имитация рестарта)."""
    a_path = str(tmp_path / "alice.db")
    b_path = str(tmp_path / "bob.db")
    av = create_vault(a_path, b"pw-a", params=FAST)
    bv = create_vault(b_path, b"pw-b", params=FAST)

    sk = b"z" * 32
    bob_priv, bob_pub = primitives.generate_x25519_keypair()
    tkey = envelope.derive_transform_key(sk)
    ca = av.conversations.add(mode="decentralized")
    cb = bv.conversations.add(mode="decentralized")
    av.ratchet.save_state(ca, ratchet.ratchet_init_alice(sk, bob_pub))
    bv.ratchet.save_state(cb, ratchet.ratchet_init_bob(sk, (bob_priv, bob_pub)))

    def send(vault, conv, text):
        state = vault.ratchet.load_state(conv)
        blob = envelope.seal(state, tkey, text)
        vault.ratchet.save_state(conv, state)
        return blob

    def recv(vault, conv, blob):
        state = vault.ratchet.load_state(conv)
        pt = envelope.open_(state, tkey, blob)
        vault.ratchet.save_state(conv, state)
        return pt

    # Alice -> Bob (несколько подряд)
    for i in range(3):
        assert recv(bv, cb, send(av, ca, f"a{i}".encode())) == f"a{i}".encode()
    # Bob -> Alice (DH-ratchet у Алисы)
    assert recv(av, ca, send(bv, cb, b"reply")) == b"reply"
    # Alice -> Bob снова, уже после реальной перезагрузки vault'ов с диска
    av.close(); bv.close()
    av = open_vault(a_path, b"pw-a")
    bv = open_vault(b_path, b"pw-b")
    assert recv(bv, cb, send(av, ca, b"after restart")) == b"after restart"
    av.close(); bv.close()


def test_out_of_order_delivery_persisted(tmp_path):
    a_path = str(tmp_path / "a.db")
    b_path = str(tmp_path / "b.db")
    av = create_vault(a_path, b"pw", params=FAST)
    bv = create_vault(b_path, b"pw", params=FAST)
    sk = b"z" * 32
    bob_priv, bob_pub = primitives.generate_x25519_keypair()
    tkey = envelope.derive_transform_key(sk)
    ca = av.conversations.add(mode="decentralized")
    cb = bv.conversations.add(mode="decentralized")
    av.ratchet.save_state(ca, ratchet.ratchet_init_alice(sk, bob_pub))
    bv.ratchet.save_state(cb, ratchet.ratchet_init_bob(sk, (bob_priv, bob_pub)))

    a = av.ratchet.load_state(ca)
    b1 = envelope.seal(a, tkey, b"m1")
    b2 = envelope.seal(a, tkey, b"m2")
    b3 = envelope.seal(a, tkey, b"m3")
    av.ratchet.save_state(ca, a)

    def recv(blob):
        st = bv.ratchet.load_state(cb)
        pt = envelope.open_(st, tkey, blob)
        bv.ratchet.save_state(cb, st)
        return pt

    assert recv(b3) == b"m3"
    assert recv(b1) == b"m1"
    assert recv(b2) == b"m2"
    av.close(); bv.close()


def test_receive_message_file_kind_round_trips(tmp_path):
    v = create_vault(str(tmp_path / "v.db"), b"pw", params=FAST)
    conv = v.conversations.add(mode="decentralized")
    _priv, pub = primitives.generate_x25519_keypair()
    state = ratchet.ratchet_init_bob(b"k" * 32, (_priv, pub))
    v.receive_message(
        conv, body=b"file-bytes", new_state=state,
        kind="file", filename="doc.pdf", mime_type="application/pdf",
    )
    row = v.messages.list(conv)[0]
    assert row["kind"] == "file"
    assert row["filename"] == "doc.pdf"
    assert row["mime_type"] == "application/pdf"
    assert row["body"] == b"file-bytes"
    v.close()
