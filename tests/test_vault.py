import pytest

from mys_storage import open_vault, create_vault, WrongPassword, VaultExists, VaultLocked

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


def test_wrong_password_increments_and_locks(tmp_path):
    path = _db(tmp_path)
    create_vault(path, b"right", params=FAST).close()
    with pytest.raises(WrongPassword):
        open_vault(path, b"nope")
    # сразу повторный вход заблокирован задержкой
    with pytest.raises(VaultLocked):
        open_vault(path, b"right")


def test_successful_open_resets_attempts(tmp_path, monkeypatch):
    path = _db(tmp_path)
    create_vault(path, b"right", params=FAST).close()
    # нулевая задержка, чтобы блокировка не мешала последовательным попыткам
    import mys_storage.vault as vault_mod
    monkeypatch.setattr(vault_mod, "_delay_for", lambda failed: 0.0)
    with pytest.raises(WrongPassword):
        open_vault(path, b"nope")
    with pytest.raises(WrongPassword):
        open_vault(path, b"nope2")
    v = open_vault(path, b"right")
    assert v._meta["attempts"]["failed"] == 0
    v.close()


def test_duress_wipe_destroys_vault(tmp_path, monkeypatch):
    path = _db(tmp_path)
    v = create_vault(path, b"right", params={**FAST})
    # включаем duress с порогом 2
    v._meta["duress"] = {"wipe_enabled": True, "threshold": 2}
    from mys_storage import sidecar as sc
    sc.write_sidecar(path + ".meta.json", v._meta)
    v.close()

    import mys_storage.vault as vault_mod
    monkeypatch.setattr(vault_mod, "_delay_for", lambda failed: 0.0)

    with pytest.raises(WrongPassword):
        open_vault(path, b"x")
    with pytest.raises(WrongPassword):
        open_vault(path, b"y")  # достигнут порог -> wipe

    import os
    assert not os.path.exists(path)
    assert not os.path.exists(path + ".meta.json")
