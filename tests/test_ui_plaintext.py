"""Чужой текст (названия комнат, имена, цитаты) — только PlainText, не HTML.

QLabel по умолчанию в режиме AutoText: строка, похожая на разметку
(``<b>``, ``<a href>``, ``<img src="file://…">``), рендерится как rich text —
собеседник мог бы подделывать вид интерфейса или подтягивать локальные файлы.
"""

from PySide6.QtCore import Qt

from mys_ui.controller import AppController
from mys_ui.widgets.p2p_banner import P2POfflineBanner
from mys_ui.widgets.top_bar import TopBar
from mys_ui.windows.main_window import MainWindow

FAST = {"time_cost": 1, "memory_cost": 8, "parallelism": 1}
HTML = '<b>жирно</b><img src="file:///etc/passwd">'


def test_external_text_labels_are_plain(qtbot, tmp_path):
    c = AppController(str(tmp_path / "v.db"), kdf_params=FAST)
    c.create_vault(b"pw")
    conv = c.create_conversation(HTML)
    w = MainWindow(c)
    qtbot.addWidget(w)
    w._on_select(conv)
    w.input.set_reply(HTML, HTML)
    assert w._chat_name.textFormat() == Qt.PlainText
    assert w._chat_name.text() == HTML
    assert w.input._reply_label.textFormat() == Qt.PlainText
    c.lock()


def test_top_bar_and_banner_plain(qtbot):
    top = TopBar()
    qtbot.addWidget(top)
    assert top.chip.textFormat() == Qt.PlainText
    banner = P2POfflineBanner()
    qtbot.addWidget(banner)
    banner.set_idle(note=HTML)
    assert banner._note.textFormat() == Qt.PlainText


def test_conversation_tooltip_escapes_html(qtbot, tmp_path):
    c = AppController(str(tmp_path / "v.db"), kdf_params=FAST)
    c.create_vault(b"pw")
    c.create_conversation(HTML)
    w = MainWindow(c)
    qtbot.addWidget(w)
    tip = w.conversations.list.item(0).toolTip()
    assert "<b>" not in tip and "&lt;b&gt;" in tip
    c.lock()
