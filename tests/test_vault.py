import pytest

from mys_storage import open_vault, create_vault, WrongPassword, VaultExists

FAST = {"time_cost": 1, "memory_cost": 8, "parallelism": 1}


def _db(tmp_path):
    return str(tmp_path / "vault.db")


def test_create_then_open_round_trip(tmp_path):
    path = _db(tmp_path)
    v = create_vault(path, b"correct horse", params=FAST)
    v.settings.set("mode", b"decentralized")
    v.close()
    v2 = open_vault(path, b"correct horse")
    assert v2.settings.get("mode") == b"decentralized"
    v2.close()


def test_open_with_wrong_password_raises(tmp_path):
    path = _db(tmp_path)
    create_vault(path, b"right", params=FAST).close()
    with pytest.raises(WrongPassword):
        open_vault(path, b"wrong")


def test_create_existing_raises(tmp_path):
    path = _db(tmp_path)
    create_vault(path, b"pw", params=FAST).close()
    with pytest.raises(VaultExists):
        create_vault(path, b"pw", params=FAST)


def test_db_file_has_no_plaintext(tmp_path):
    path = _db(tmp_path)
    v = create_vault(path, b"pw", params=FAST)
    v.settings.set("marker", b"SUPER_SECRET_PLAINTEXT")
    v.close()
    raw = open(path, "rb").read()
    assert b"SUPER_SECRET_PLAINTEXT" not in raw
    assert b"SQLite format 3" not in raw  # зашифрованный заголовок
