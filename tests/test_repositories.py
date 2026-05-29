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
    v.messages.set_status(m1, "delivered")
    assert v.messages.list(conv)[0]["status"] == "delivered"
    v.close()
