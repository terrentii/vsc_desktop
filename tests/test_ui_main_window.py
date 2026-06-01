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


class _FakeP2PSvc:
    def __init__(self, vault, rendezvous_url, *, on_message, on_state_change, on_error):
        self._vault = vault
        self.on_message = on_message
        self.started = False
        self.stopped = False
        self.sessions: dict[int, str] = {}

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def start_session(self, phrase, *, timeout=None):
        cid = self._vault.conversations.add(
            mode=DECENTRALIZED, title=phrase
        )
        self.sessions[cid] = phrase
        return cid

    def has_session(self, cid):
        return cid in self.sessions


def _p2p_window(tmp_path):
    c = AppController(
        str(tmp_path / "v.db"), kdf_params=FAST, p2p_factory=_FakeP2PSvc
    )
    c.create_vault(b"pw")
    c.set_mode(DECENTRALIZED)
    return c


def test_p2p_connect_worker_creates_conversation(qtbot, tmp_path):
    c = _p2p_window(tmp_path)
    w = MainWindow(c)
    qtbot.addWidget(w)
    with qtbot.waitSignal(w._p2p_bridge.started, timeout=2000) as blocker:
        w._p2p_connect_worker("общая фраза", "ws://a:1/p2p")
    assert blocker.args == [True, ""]
    assert len(c.list_conversations()) == 1
    c.lock()


def test_p2p_connect_worker_reports_failure(qtbot, tmp_path, monkeypatch):
    c = _p2p_window(tmp_path)
    w = MainWindow(c)
    qtbot.addWidget(w)

    warnings: list[tuple] = []
    monkeypatch.setattr(
        "mys_ui.windows.main_window.QMessageBox.warning",
        lambda *a, **k: warnings.append(a),
    )

    def boom(*a, **k):
        raise RuntimeError("нет связи")

    monkeypatch.setattr(c, "create_conversation", boom)
    with qtbot.waitSignal(w._p2p_bridge.started, timeout=2000) as blocker:
        w._p2p_connect_worker("ф", "ws://a:1/p2p")
    assert blocker.args[0] is False
    assert "нет связи" in blocker.args[1]
    assert warnings and "нет связи" in warnings[0][-1]
    c.lock()


def test_p2p_incoming_message_refreshes(qtbot, tmp_path):
    c = _p2p_window(tmp_path)
    w = MainWindow(c)
    qtbot.addWidget(w)
    # Поднять сервис и сессию, выбрать беседу.
    cid = c.create_conversation(
        "ф", room_phrase="общая фраза", rendezvous_url="ws://a:1/p2p"
    )
    # Положить входящее в vault, как сделал бы сервис, затем дёрнуть колбэк.
    ping = "пинг".encode()
    c.vault.messages.add(cid, direction="in", body=ping, status="received")
    w._on_select(cid)
    before = w.chat.count()
    with qtbot.waitSignal(w._p2p_bridge.message, timeout=2000):
        c._p2p_on_message(cid, ping)
    assert w.chat.count() >= before
    c.lock()


def test_p2p_state_and_error_observers_arity(qtbot, tmp_path):
    # Сервис зовёт on_state_change/on_error с (conv_id, value); лямбды-наблюдатели
    # окна должны принимать оба аргумента, иначе TypeError в рантайме.
    c = _p2p_window(tmp_path)
    w = MainWindow(c)
    qtbot.addWidget(w)
    with qtbot.waitSignal(w._p2p_bridge.state, timeout=1000):
        c._p2p_on_state(1, "connected")
    with qtbot.waitSignal(w._p2p_bridge.error, timeout=1000):
        c._p2p_on_error(1, RuntimeError("boom"))
    assert w._p2p_state == "connected"
    assert "boom" in w._p2p_error
    c.lock()
