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
