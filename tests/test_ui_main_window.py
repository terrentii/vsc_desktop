from mys_ui.controller import AppController, CENTRALIZED, DECENTRALIZED
from mys_ui.windows.main_window import MainWindow

FAST = {"time_cost": 1, "memory_cost": 8, "parallelism": 1}


def _ready(tmp_path):
    c = AppController(str(tmp_path / "v.db"), kdf_params=FAST)
    c.create_vault(b"pw")
    return c


def test_conversation_list_populates(qtbot, tmp_path):
    c = _ready(tmp_path)
    c.create_conversation("Алиса")
    c.create_conversation("Боб")
    w = MainWindow(c)
    qtbot.addWidget(w)
    assert w.conversations.list.count() == 2
    c.lock()


def test_select_and_send(qtbot, tmp_path):
    c = _ready(tmp_path)
    conv = c.create_conversation("чат")
    w = MainWindow(c)
    qtbot.addWidget(w)
    w._on_select(conv)
    w.input.field.setText("привет")
    w.input.btn_send.click()
    assert w.chat.count() == 1
    assert "привет" in w.chat.item(0).text()
    assert len(c.list_messages(conv)) == 1
    c.lock()


def test_mode_toggle_filters(qtbot, tmp_path):
    c = _ready(tmp_path)
    c.set_mode(DECENTRALIZED)
    c.create_conversation("p2p")
    c.set_mode(CENTRALIZED)
    c.create_conversation("central")
    c.set_mode(DECENTRALIZED)
    w = MainWindow(c)
    qtbot.addWidget(w)
    assert w.conversations.list.count() == 1
    assert w.conversations.list.item(0).text() == "p2p"
    w.top._select(CENTRALIZED)
    assert w.conversations.list.count() == 1
    assert w.conversations.list.item(0).text() == "central"
    assert c.mode == CENTRALIZED
    c.lock()


def test_lock_emits_signal(qtbot, tmp_path):
    c = _ready(tmp_path)
    w = MainWindow(c)
    qtbot.addWidget(w)
    with qtbot.waitSignal(w.locked, timeout=1000):
        w.top.btn_lock.click()
    c.lock()


def test_file_message_renders_as_attachment_row(qtbot, tmp_path):
    c = _ready(tmp_path)
    conv = c.create_conversation("чат")
    c.send_file(conv, "photo.png", "image/png", b"\x89PNG\x00\x00")
    w = MainWindow(c)
    qtbot.addWidget(w)
    w._on_select(conv)
    assert w.chat.count() == 1
    assert "photo.png" in w.chat.item(0).text()
    c.lock()


def test_delete_conversation_clears_current_and_refreshes(qtbot, tmp_path, monkeypatch):
    from mys_ui.dialogs import common

    monkeypatch.setattr(common, "confirm", lambda *a, **k: True)

    c = _ready(tmp_path)
    conv = c.create_conversation("чат")
    w = MainWindow(c)
    qtbot.addWidget(w)
    w._on_select(conv)
    assert w._current == conv

    w._on_delete_conversation(conv)

    assert w._current is None
    assert w.chat.count() == 0
    assert w.conversations.list.count() == 0
    assert c.list_conversations() == []
    c.lock()


def test_favorites_pinned_on_top(qtbot):
    from mys_ui.widgets.conversation_list import ConversationList

    lst = ConversationList()
    qtbot.addWidget(lst)
    lst.populate([
        {"id": 1, "title": "Тест"},
        {"id": 2, "title": "Избранное"},
        {"id": 3, "title": "Volounteers"},
    ])
    titles = [lst.list.item(i).text() for i in range(lst.list.count())]
    assert titles == ["Избранное", "Тест", "Volounteers"]


# --- P2P: онлайн-индикатор, плашка офлайн, подключение/реконнект с таймером ----

class _FakeP2PServiceForWindow:
    """Двойник P2PService для тестов MainWindow — синхронный, без своего потока
    (MainWindow сама уводит вызовы в threading.Thread; тут это неважно, т.к.
    методы мгновенные)."""

    def __init__(self):
        self.resolve_result = 501
        self.start_result = 501
        self.resolved: list[str] = []
        self.started: list[tuple[str, float | None]] = []
        self.reconnected: list[tuple[int, float | None]] = []
        self.start_error: Exception | None = None
        self.reconnect_error: Exception | None = None
        self._active: set[int] = set()

    def resolve_conversation(self, phrase: str) -> int:
        self.resolved.append(phrase)
        return self.resolve_result

    def start_session(self, phrase: str, *, timeout=None) -> int:
        self.started.append((phrase, timeout))
        if self.start_error is not None:
            raise self.start_error
        self._active.add(self.start_result)
        return self.start_result

    def reconnect(self, conversation_id: int, *, timeout=None) -> None:
        self.reconnected.append((conversation_id, timeout))
        if self.reconnect_error is not None:
            raise self.reconnect_error
        self._active.add(conversation_id)

    def has_session(self, conversation_id: int) -> bool:
        return conversation_id in self._active

    def stop_session(self, conversation_id: int) -> None:
        self._active.discard(conversation_id)

    def send(self, conversation_id, text):
        pass

    def send_file(self, conversation_id, filename, mime_type, data):
        pass

    def stop(self) -> None:
        pass


def test_p2p_new_channel_shows_connecting_then_chat_on_success(qtbot, tmp_path):
    c = _ready(tmp_path)
    fake = _FakeP2PServiceForWindow()
    c.attach_service(fake)
    w = MainWindow(c)
    qtbot.addWidget(w)

    w._begin_p2p_connect(phrase="общая фраза")

    assert w._current == fake.resolve_result
    assert w._chat_stack.currentIndex() == 2  # окно ожидания, не чат
    assert not w.p2p_banner._countdown.isHidden()

    qtbot.waitUntil(lambda: w._p2p_online.get(fake.resolve_result) is True, timeout=2000)
    assert fake.started == [("общая фраза", 300)]
    assert w._chat_stack.currentIndex() == 1  # переключилось на сам чат
    c.lock()


def test_p2p_new_channel_shows_idle_banner_with_note_on_failure(qtbot, tmp_path):
    c = _ready(tmp_path)
    fake = _FakeP2PServiceForWindow()
    fake.start_error = RuntimeError("пир не вошёл в комнату за отведённый таймаут")
    c.attach_service(fake)
    w = MainWindow(c)
    qtbot.addWidget(w)

    w._begin_p2p_connect(phrase="фраза")
    qtbot.waitUntil(lambda: w._p2p_online.get(fake.resolve_result) is False, timeout=2000)

    assert w._chat_stack.currentIndex() == 2
    assert not w.p2p_banner._btn_reconnect.isHidden()  # вернулись к кнопке, не к отсчёту
    assert not w.p2p_banner._note.isHidden()
    c.lock()


def test_p2p_offline_conversation_shows_banner_on_select(qtbot, tmp_path):
    c = _ready(tmp_path)
    conv = c.create_conversation("канал")
    w = MainWindow(c)
    qtbot.addWidget(w)

    w._on_select(conv)

    assert w._chat_stack.currentIndex() == 2
    assert not w.p2p_banner._btn_reconnect.isHidden()
    c.lock()


def test_p2p_reconnect_button_triggers_service_reconnect(qtbot, tmp_path):
    c = _ready(tmp_path)
    conv = c.create_conversation("канал")
    fake = _FakeP2PServiceForWindow()
    c.attach_service(fake)
    w = MainWindow(c)
    qtbot.addWidget(w)
    w._on_select(conv)

    w.p2p_banner.reconnect_requested.emit()

    assert w._chat_stack.currentIndex() == 2  # ещё окно ожидания
    qtbot.waitUntil(lambda: w._p2p_online.get(conv) is True, timeout=2000)
    assert fake.reconnected == [(conv, 300)]
    assert w._chat_stack.currentIndex() == 1
    c.lock()


def test_p2p_read_history_dismisses_banner_and_shows_chat(qtbot, tmp_path):
    c = _ready(tmp_path)
    conv = c.create_conversation("канал")
    w = MainWindow(c)
    qtbot.addWidget(w)
    w._on_select(conv)
    assert w._chat_stack.currentIndex() == 2

    w.p2p_banner.read_history_requested.emit()

    assert w._chat_stack.currentIndex() == 1
    assert w._p2p_banner_dismissed_for == conv
    c.lock()


def test_p2p_banner_reappears_on_reselect(qtbot, tmp_path):
    c = _ready(tmp_path)
    conv1 = c.create_conversation("первый")
    conv2 = c.create_conversation("второй")
    w = MainWindow(c)
    qtbot.addWidget(w)

    w._on_select(conv1)
    w.p2p_banner.read_history_requested.emit()
    assert w._chat_stack.currentIndex() == 1  # переписка открыта

    w._on_select(conv2)
    w._on_select(conv1)  # снова зашли в conv1 — дисмисс не переживает визит

    assert w._chat_stack.currentIndex() == 2
    c.lock()


def test_p2p_reconnect_double_click_ignored_while_connecting(qtbot, tmp_path):
    c = _ready(tmp_path)
    conv = c.create_conversation("канал")
    fake = _FakeP2PServiceForWindow()
    c.attach_service(fake)
    w = MainWindow(c)
    qtbot.addWidget(w)
    w._on_select(conv)

    w.p2p_banner.reconnect_requested.emit()
    w.p2p_banner.reconnect_requested.emit()  # повторный клик, пока идёт попытка

    qtbot.waitUntil(lambda: w._p2p_online.get(conv) is True, timeout=2000)
    assert len(fake.reconnected) == 1  # второй клик не породил второй вызов
    c.lock()


def test_p2p_live_disconnect_updates_dot_without_interrupting_dismissed_view(qtbot, tmp_path):
    c = _ready(tmp_path)
    conv = c.create_conversation("канал")
    w = MainWindow(c)
    qtbot.addWidget(w)
    w._on_select(conv)
    w.p2p_banner.read_history_requested.emit()  # смотрим переписку офлайн-беседы
    assert w._chat_stack.currentIndex() == 1

    w._on_p2p_state(conv, "connected")
    assert w._chat_online.text() == "● В СЕТИ"
    assert w._chat_stack.currentIndex() == 1

    w._on_p2p_state(conv, "disconnected")  # обрыв на лету — не выдёргивает плашку
    assert w._chat_online.text() == "● НЕ В СЕТИ"
    assert w._chat_stack.currentIndex() == 1
    c.lock()


def test_p2p_service_unavailable_warns_instead_of_crashing(qtbot, tmp_path, monkeypatch):
    from mys_ui.dialogs import common

    warned = []
    monkeypatch.setattr(common, "warn", lambda *a, **k: warned.append(a))

    c = _ready(tmp_path)  # без attach_service и без p2p_factory
    w = MainWindow(c)
    qtbot.addWidget(w)

    w._begin_p2p_connect(phrase="фраза")

    assert warned  # предупреждение показано, а не исключение наружу
    assert w._current is None
    c.lock()
