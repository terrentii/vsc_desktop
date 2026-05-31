"""UI-тесты централизованного режима (этап 6), headless через offscreen.

Используем фейковый централизованный сервис (без сети) через central_factory,
чтобы проверить вход, отображение комнат, отправку и real-time без сервера.
"""

from mys_centralized.account import save_session
from mys_centralized.errors import AuthError
from mys_centralized.models import Session
from mys_ui.controller import CENTRALIZED, AppController
from mys_ui.dialogs.settings import SettingsDialog
from mys_ui.windows import main_window
from mys_ui.windows.main_window import MainWindow

FAST = {"time_cost": 1, "memory_cost": 8, "parallelism": 1}


class FakeCentral:
    """Имитация CentralizedService поверх реального vault (без сети/потоков)."""

    def __init__(self, vault, *, on_message, on_state_change, on_error):
        self.vault = vault
        self._on_message = on_message
        self._on_state_change = on_state_change
        self._on_error = on_error
        self.session: Session | None = None
        self.started = False
        self.logged_out = False

    def start(self):
        self.started = True

    def stop(self):
        self.started = False

    def login(self, server_url, username, password, *, register=False):
        if password == "bad":
            raise AuthError("invalid_credentials")
        self.session = Session(
            server_url=server_url, username=username, user_id=1, token="tok"
        )
        # имитируем синк: одна комната с историей
        conv = self.vault.conversations.add(
            mode="centralized", room_id=b"1", title="general"
        )
        self.vault.messages.add(
            conv, direction="in", body=b"history", status="received", wire_seq=1
        )
        self._on_state_change("synced")
        return self.session

    def resume(self):
        # Боевой сервис грузит сессию из vault; имитируем то же + первичный синк.
        from mys_centralized.account import load_session
        sess = load_session(self.vault)
        if sess is None:
            return None
        self.session = sess
        if self.vault.conversations.get_by_room_id(b"1", mode="centralized") is None:
            conv = self.vault.conversations.add(
                mode="centralized", room_id=b"1", title="general"
            )
            self.vault.messages.add(
                conv, direction="in", body=b"history", status="received", wire_seq=1
            )
        self._on_state_change("synced")
        return self.session

    def logout(self):
        # Боевой сервис: забыть сессию + (по настройке) стереть локальный кэш.
        from mys_centralized.account import (
            clear_session, load_wipe_on_logout, wipe_local_cache,
        )
        self.session = None
        self.logged_out = True
        clear_session(self.vault)
        if load_wipe_on_logout(self.vault):
            wipe_local_cache(self.vault)

    def send_message(self, conversation_id, body):
        lid = self.vault.messages.add(
            conversation_id, direction="out", body=body.encode("utf-8"), status="sent"
        )
        return lid

    # тестовый помощник: «прилетело» live-сообщение
    def deliver(self, conversation_id, body):
        lid = self.vault.messages.add(
            conversation_id, direction="in", body=body.encode("utf-8"),
            status="received", wire_seq=99,
        )
        self._on_message(conversation_id, lid)


def _ready(tmp_path):
    holder = {}

    def factory(vault, **cb):
        svc = FakeCentral(vault, **cb)
        holder["svc"] = svc
        return svc

    c = AppController(str(tmp_path / "v.db"), kdf_params=FAST, central_factory=factory)
    c.create_vault(b"pw")
    return c, holder


def test_central_login_populates_rooms(qtbot, tmp_path):
    c, holder = _ready(tmp_path)
    w = MainWindow(c)
    qtbot.addWidget(w)
    c.set_mode(CENTRALIZED)  # переключение в Центр (нет сессии)
    # без модального диалога — выполняем вход напрямую
    assert w._perform_central_login("https://soufos.ru", "alice", "pw", False) is True
    assert holder["svc"].started is True
    assert c.central_session() is not None
    assert w.conversations.list.count() == 1
    assert w.conversations.list.item(0).text() == "general"
    c.lock()


def test_central_login_bad_credentials_shows_error(qtbot, tmp_path):
    c, _ = _ready(tmp_path)
    w = MainWindow(c)
    qtbot.addWidget(w)
    c.set_mode(CENTRALIZED)
    assert w._perform_central_login("https://soufos.ru", "alice", "bad", False) is False
    assert w._central_error == "invalid_credentials"
    assert c.central_session() is None
    assert w.conversations.list.count() == 0
    c.lock()


def test_central_live_message_refreshes_chat(qtbot, tmp_path):
    c, holder = _ready(tmp_path)
    w = MainWindow(c)
    qtbot.addWidget(w)
    c.set_mode(CENTRALIZED)
    w._perform_central_login("https://soufos.ru", "alice", "pw", False)
    conv = c.list_conversations()[0]["id"]
    w._on_select(conv)
    assert w.chat.count() == 1  # история
    holder["svc"].deliver(conv, "live!")
    assert w.chat.count() == 2
    assert "live!" in w.chat.item(1).text()
    c.lock()


def test_central_send_routes_through_service(qtbot, tmp_path):
    c, holder = _ready(tmp_path)
    w = MainWindow(c)
    qtbot.addWidget(w)
    c.set_mode(CENTRALIZED)
    w._perform_central_login("https://soufos.ru", "alice", "pw", False)
    conv = c.list_conversations()[0]["id"]
    w._on_select(conv)
    w.input.field.setText("привет")
    w.input.btn_send.click()
    msgs = c.list_messages(conv)
    out = [m for m in msgs if m["direction"] == "out"]
    assert len(out) == 1 and out[0]["body"].decode() == "привет"
    assert out[0]["status"] == "sent"  # прошло через сервис, не локальная заглушка
    c.lock()


def test_mode_switch_without_session_prompts_login(qtbot, tmp_path):
    c, _ = _ready(tmp_path)
    w = MainWindow(c)
    qtbot.addWidget(w)
    calls = []
    w._central_login = lambda: calls.append(True)  # подменяем модальный вход
    w.top._select(CENTRALIZED)  # реальный _on_mode → нет сессии → форма входа
    assert calls == [True]
    c.lock()


def test_lock_stops_central_service(qtbot, tmp_path):
    c, holder = _ready(tmp_path)
    w = MainWindow(c)
    qtbot.addWidget(w)
    c.set_mode(CENTRALIZED)
    w._perform_central_login("https://soufos.ru", "alice", "pw", False)
    svc = holder["svc"]
    assert svc.started is True
    c.lock()
    assert svc.started is False


class _SyncThread:
    """Подмена threading.Thread: выполняет тело синхронно при start()."""

    def __init__(self, *, target, **_kw):
        self._target = target

    def start(self):
        self._target()


def test_auto_resume_restores_saved_session(qtbot, tmp_path, monkeypatch):
    c, holder = _ready(tmp_path)
    # Сохранённая сессия в vault — как после прошлого входа.
    save_session(
        c.vault,
        Session(server_url="https://soufos.ru", username="alice", user_id=1, token="tok"),
    )
    assert c.central_has_saved_session() is True
    # Фоновый поток resume выполняем синхронно для детерминизма.
    monkeypatch.setattr(main_window.threading, "Thread", _SyncThread)

    w = MainWindow(c)  # __init__ → _try_auto_resume → resume
    qtbot.addWidget(w)

    assert c.central_session() is not None
    assert holder["svc"].started is True
    # Переключение в «Центр» НЕ должно открывать форму входа (сессия уже есть).
    calls = []
    w._central_login = lambda: calls.append(True)
    w.top._select(CENTRALIZED)
    assert calls == []
    assert w.conversations.list.count() == 1
    assert w.conversations.list.item(0).text() == "general"
    c.lock()


def test_no_auto_resume_without_saved_session(qtbot, tmp_path, monkeypatch):
    c, holder = _ready(tmp_path)
    assert c.central_has_saved_session() is False
    monkeypatch.setattr(main_window.threading, "Thread", _SyncThread)

    w = MainWindow(c)  # нет сохранённой сессии → resume не запускается
    qtbot.addWidget(w)

    assert c.central_session() is None
    assert "svc" not in holder  # сервис даже не создавался
    c.lock()


def test_settings_wipe_toggle_persists(qtbot, tmp_path):
    c, _ = _ready(tmp_path)
    w = MainWindow(c)
    qtbot.addWidget(w)
    d = SettingsDialog(c, w)
    qtbot.addWidget(d)
    assert d.wipe_on_logout.isChecked() is False  # по умолчанию история остаётся
    d.wipe_on_logout.setChecked(True)
    assert c.central_wipe_on_logout() is True
    c.lock()


def test_settings_logout_wipes_history_when_enabled(qtbot, tmp_path):
    c, holder = _ready(tmp_path)
    w = MainWindow(c)
    qtbot.addWidget(w)
    c.set_mode(CENTRALIZED)
    w._perform_central_login("https://soufos.ru", "alice", "pw", False)
    assert len(c.list_conversations()) == 1
    c.set_central_wipe_on_logout(True)

    d = SettingsDialog(c, w)
    qtbot.addWidget(d)
    assert d.btn_logout.isEnabled() is True
    d._logout()

    assert c.central_session() is None
    assert c.list_conversations() == []  # история стёрта
    c.lock()


def test_settings_logout_keeps_history_by_default(qtbot, tmp_path):
    c, holder = _ready(tmp_path)
    w = MainWindow(c)
    qtbot.addWidget(w)
    c.set_mode(CENTRALIZED)
    w._perform_central_login("https://soufos.ru", "alice", "pw", False)

    d = SettingsDialog(c, w)
    qtbot.addWidget(d)
    d._logout()

    assert c.central_session() is None
    assert len(c.list_conversations()) == 1  # история осталась для офлайн-чтения
    c.lock()
