from mys_ui.controller import AppController
from mys_ui.windows.unlock import UnlockWindow

FAST = {"time_cost": 1, "memory_cost": 8, "parallelism": 1}


def test_create_vault_via_unlock_window(qtbot, tmp_path):
    c = AppController(str(tmp_path / "v.db"), kdf_params=FAST)
    w = UnlockWindow(c)
    qtbot.addWidget(w)
    assert w._creating is True
    w.password.setText("pw")
    w.confirm.setText("pw")
    with qtbot.waitSignal(w.unlocked, timeout=3000):
        w.submit.click()
    assert c.vault is not None
    c.lock()


def test_create_password_mismatch_shows_error(qtbot, tmp_path):
    c = AppController(str(tmp_path / "v.db"), kdf_params=FAST)
    w = UnlockWindow(c)
    qtbot.addWidget(w)
    w.password.setText("a")
    w.confirm.setText("b")
    w.submit.click()
    assert "не совпад" in w.error.text().lower()
    assert c.vault is None


def test_unlock_wrong_password_shows_error(qtbot, tmp_path):
    path = str(tmp_path / "v.db")
    setup = AppController(path, kdf_params=FAST)
    setup.create_vault(b"right")
    setup.lock()

    c = AppController(path, kdf_params=FAST)
    w = UnlockWindow(c)
    qtbot.addWidget(w)
    assert w._creating is False
    w.password.setText("wrong")
    w.submit.click()
    assert "неверный" in w.error.text().lower()
    assert c.vault is None
