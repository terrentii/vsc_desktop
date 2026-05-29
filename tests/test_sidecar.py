import base64

from mys_storage import sidecar


def test_new_sidecar_has_random_salt_and_defaults():
    a = sidecar.new_sidecar()
    b = sidecar.new_sidecar()
    assert a["format_version"] == 1
    assert a["kdf"]["algo"] == "argon2id"
    assert len(base64.b64decode(a["kdf"]["salt"])) == 16
    assert a["kdf"]["salt"] != b["kdf"]["salt"]          # соль случайна
    assert a["attempts"] == {"failed": 0, "lockout_until": None}
    assert a["duress"]["wipe_enabled"] is False


def test_write_read_round_trip(tmp_path):
    meta = sidecar.new_sidecar()
    path = tmp_path / "v.meta.json"
    sidecar.write_sidecar(str(path), meta)
    assert sidecar.read_sidecar(str(path)) == meta


def test_write_is_atomic_no_partial_file(tmp_path):
    path = tmp_path / "v.meta.json"
    sidecar.write_sidecar(str(path), sidecar.new_sidecar())
    # временный файл не остаётся рядом
    assert list(p.name for p in tmp_path.iterdir()) == ["v.meta.json"]
