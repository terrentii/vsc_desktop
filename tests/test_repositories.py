from mys_crypto.secure import SecureBytes
from mys_storage import kdf


def test_derive_db_key_deterministic_and_secure():
    salt = b"saltsaltsaltsalt"
    k1 = kdf.derive_db_key(b"pw", salt, time_cost=1, memory_cost=8, parallelism=1, hash_len=32)
    k2 = kdf.derive_db_key(b"pw", salt, time_cost=1, memory_cost=8, parallelism=1, hash_len=32)
    assert isinstance(k1, SecureBytes)
    assert bytes(k1) == bytes(k2)
    assert len(k1) == 32


def test_derive_db_key_salt_sensitive():
    a = kdf.derive_db_key(b"pw", b"AAAAAAAAAAAAAAAA", time_cost=1, memory_cost=8, parallelism=1)
    b = kdf.derive_db_key(b"pw", b"BBBBBBBBBBBBBBBB", time_cost=1, memory_cost=8, parallelism=1)
    assert bytes(a) != bytes(b)


from mys_storage import create_vault

FAST = {"time_cost": 1, "memory_cost": 8, "parallelism": 1}


def _vault(tmp_path):
    return create_vault(str(tmp_path / "v.db"), b"pw", params=FAST)


def test_identities_crud(tmp_path):
    v = _vault(tmp_path)
    iid = v.identities.add(kind="x25519", public_key=b"P" * 32, private_key=b"S" * 32, label="me")
    row = v.identities.get(iid)
    assert row["kind"] == "x25519" and row["public_key"] == b"P" * 32
    v.close()


def test_contacts_and_conversations_and_messages(tmp_path):
    v = _vault(tmp_path)
    cid = v.contacts.add(public_key=b"K" * 32, fingerprint="ab:cd", alias="bob")
    conv = v.conversations.add(mode="decentralized", peer_contact_id=cid, title="bob")
    m1 = v.messages.add(conv, direction="out", body=b"hi", status="sent")
    v.messages.add(conv, direction="in", body=b"yo", status="received")
    msgs = v.messages.list(conv)
    assert [m["body"] for m in msgs] == [b"hi", b"yo"]
    assert [m["kind"] for m in msgs] == ["text", "text"]
    v.messages.set_status(m1, "delivered")
    assert v.messages.list(conv)[0]["status"] == "delivered"
    v.close()


def test_messages_add_file_kind_round_trips(tmp_path):
    v = _vault(tmp_path)
    conv = v.conversations.add(mode="decentralized")
    v.messages.add(
        conv, direction="out", body=b"\x89PNG-bytes", status="sent",
        kind="file", filename="photo.png", mime_type="image/png",
    )
    row = v.messages.list(conv)[0]
    assert row["kind"] == "file"
    assert row["filename"] == "photo.png"
    assert row["mime_type"] == "image/png"
    assert row["body"] == b"\x89PNG-bytes"
    v.close()


def test_messages_lazy_image_backfilled_via_set_body(tmp_path):
    v = _vault(tmp_path)
    conv = v.conversations.add(mode="centralized")
    mid = v.messages.add(
        conv, direction="in", body=None, status="received",
        kind="image", filename="photo.png", mime_type="image/png",
        media_ref="abc123_photo.png",
    )
    row = v.messages.get(mid)
    assert row["kind"] == "image"
    assert row["media_ref"] == "abc123_photo.png"
    assert row["body"] is None

    v.messages.set_body(mid, b"\x89PNG-real-bytes")
    refreshed = v.messages.list(conv)[0]
    assert refreshed["body"] == b"\x89PNG-real-bytes"
    v.close()


def test_ratchet_repo_delete(tmp_path):
    from mys_crypto import primitives, ratchet

    v = _vault(tmp_path)
    conv = v.conversations.add(mode="decentralized")
    _priv, pub = primitives.generate_x25519_keypair()
    v.ratchet.save_state(conv, ratchet.ratchet_init_alice(b"k" * 32, pub))
    assert v.ratchet.load_state(conv) is not None
    v.ratchet.delete(conv)
    assert v.ratchet.load_state(conv) is None
    v.close()


def test_conversation_rename(tmp_path):
    v = _vault(tmp_path)
    conv = v.conversations.add(mode="decentralized", title="старое имя")
    v.conversations.rename(conv, "новое имя")
    assert v.conversations.get(conv)["title"] == "новое имя"
    v.close()


def test_conversation_set_prs_round_trip(tmp_path):
    v = _vault(tmp_path)
    conv = v.conversations.add(mode="decentralized", room_id=b"room-id")
    assert v.conversations.get(conv)["p2p_prs"] is None
    v.conversations.set_prs(conv, b"p" * 32)
    assert v.conversations.get(conv)["p2p_prs"] == b"p" * 32
    v.close()
