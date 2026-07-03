"""P2POfflineBanner: подсостояния idle/connecting, сигналы, обратный отсчёт.

``isVisible()`` в Qt требует показанного окна целиком (не годится headless без
``.show()``) — используем ``isHidden()``, отражающий явный флаг самого виджета.
"""

from mys_ui.widgets.p2p_banner import P2POfflineBanner


def test_initial_state_is_idle(qtbot):
    b = P2POfflineBanner()
    qtbot.addWidget(b)
    assert not b._btn_reconnect.isHidden()
    assert b._countdown.isHidden()


def test_start_countdown_hides_button_shows_timer(qtbot):
    b = P2POfflineBanner()
    qtbot.addWidget(b)
    b.start_countdown(299)
    assert b._btn_reconnect.isHidden()
    assert not b._countdown.isHidden()
    assert b._countdown.text() == "4:59"


def test_countdown_renders_mm_ss_padding():
    b = P2POfflineBanner()
    b.start_countdown(65)
    assert b._countdown.text() == "1:05"
    b.start_countdown(5)
    assert b._countdown.text() == "0:05"
    b.start_countdown(0)
    assert b._countdown.text() == "0:00"


def test_set_idle_after_countdown_restores_button(qtbot):
    b = P2POfflineBanner()
    qtbot.addWidget(b)
    b.start_countdown(120)
    b.set_idle()
    assert not b._btn_reconnect.isHidden()
    assert b._countdown.isHidden()
    assert not b._timer.isActive()


def test_set_idle_with_note_shows_it():
    b = P2POfflineBanner()
    b.set_idle(note="Собеседник не вышел на связь.")
    assert not b._note.isHidden()
    assert "не вышел" in b._note.text()


def test_set_idle_without_note_hides_it():
    b = P2POfflineBanner()
    b.set_idle(note="что-то")
    b.set_idle()  # без note — предыдущая заметка не должна остаться видимой
    assert b._note.isHidden()


def test_reconnect_button_emits_signal(qtbot):
    b = P2POfflineBanner()
    qtbot.addWidget(b)
    received = []
    b.reconnect_requested.connect(lambda: received.append(True))
    b._btn_reconnect.click()
    assert received == [True]


def test_read_history_link_emits_signal_in_idle_state(qtbot):
    b = P2POfflineBanner()
    qtbot.addWidget(b)
    received = []
    b.read_history_requested.connect(lambda: received.append(True))
    b._link_history.linkActivated.emit("#")
    assert received == [True]


def test_read_history_link_available_during_countdown(qtbot):
    """«Прочитать переписку» должна работать и во время ожидания пира —
    снимает оверлей, не прерывая попытку подключения в фоне."""
    b = P2POfflineBanner()
    qtbot.addWidget(b)
    b.start_countdown(200)
    received = []
    b.read_history_requested.connect(lambda: received.append(True))
    assert not b._link_history.isHidden()
    b._link_history.linkActivated.emit("#")
    assert received == [True]


def test_tick_decrements_and_stops_at_zero(qtbot):
    b = P2POfflineBanner()
    qtbot.addWidget(b)
    b.start_countdown(1)
    b._tick()
    assert b._countdown.text() == "0:00"
    assert not b._timer.isActive()
