"""Поведение как в Telegram Desktop: клавиши поля, черновики, переход между чатами, вставка."""

from PySide6.QtCore import QMimeData, Qt
from PySide6.QtGui import QColor, QImage

from mys_ui.controller import AppController
from mys_ui.dialogs import attach
from mys_ui.windows.main_window import MainWindow

FAST = {"time_cost": 1, "memory_cost": 8, "parallelism": 1}


def _window(qtbot, tmp_path, n=2):
    c = AppController(str(tmp_path / "v.db"), kdf_params=FAST)
    c.create_vault(b"pw")
    ids = [c.create_conversation(f"чат {i}") for i in range(n)]
    w = MainWindow(c)
    qtbot.addWidget(w)
    return c, w, ids


def test_enter_sends_shift_enter_newline(qtbot, tmp_path):
    c, w, (a, _) = _window(qtbot, tmp_path)
    w._on_select(a)
    f = w.input.field
    f.insertPlainText("раз")
    qtbot.keyClick(f, Qt.Key_Return, Qt.ShiftModifier)
    f.insertPlainText("два")
    assert f.toPlainText() == "раз\nдва"
    qtbot.keyClick(f, Qt.Key_Return)
    assert [m["body"].decode() for m in c.list_messages(a)] == ["раз\nдва"]
    assert f.toPlainText() == ""
    c.lock()


def test_drafts_survive_switching_and_are_marked(qtbot, tmp_path):
    c, w, (a, b) = _window(qtbot, tmp_path)
    w._on_select(a)
    w.input.set_text("недописал")
    w._on_select(b)
    assert w.input.text() == ""
    labels = [w.conversations.list.item(i).text() for i in range(w.conversations.list.count())]
    assert any("черновик" in t for t in labels)
    w._on_select(a)
    assert w.input.text() == "недописал"
    c.lock()


def test_escape_cancels_reply_then_closes_chat(qtbot, tmp_path):
    c, w, (a, _) = _window(qtbot, tmp_path)
    w._on_select(a)
    w.input.set_reply("bob", "цитата")
    qtbot.keyClick(w.input.field, Qt.Key_Escape)
    assert w._current == a  # первый Esc снял ответ
    qtbot.keyClick(w.input.field, Qt.Key_Escape)
    assert w._current is None
    c.lock()


def test_step_chat_cycles(qtbot, tmp_path):
    c, w, ids = _window(qtbot, tmp_path, 3)
    order = w.conversations.ids()
    w._on_select(order[0])
    w._step_chat(1)
    assert w._current == order[1]
    w._step_chat(-1)
    w._step_chat(-1)
    assert w._current == order[-1]  # по кругу
    c.lock()


def test_paste_image_previews_and_sends_png(qtbot, tmp_path, monkeypatch):
    c, w, (a, _) = _window(qtbot, tmp_path)
    w._on_select(a)
    sent = []
    monkeypatch.setattr(attach.AttachDialog, "exec", lambda self: 1)
    monkeypatch.setattr(w, "_on_send_file", sent.append)
    img = QImage(8, 8, QImage.Format_RGB32)
    img.fill(QColor("red"))
    md = QMimeData()
    md.setImageData(img)
    w.input.field.insertFromMimeData(md)
    assert len(sent) == 1
    name, data = sent[0]
    assert name.endswith(".png") and data.startswith(b"\x89PNG")
    c.lock()


def test_drop_files_go_through_preview(qtbot, tmp_path, monkeypatch):
    c, w, (a, _) = _window(qtbot, tmp_path)
    w._on_select(a)
    p = tmp_path / "отчёт.txt"
    p.write_text("x")
    sent = []
    monkeypatch.setattr(attach.AttachDialog, "exec", lambda self: 1)
    monkeypatch.setattr(w, "_on_send_file", sent.append)
    w.input.files_submitted.emit([str(p), str(tmp_path / "нет.txt")])
    assert sent == [str(p)]  # несуществующий отброшен
    assert MainWindow._load_source(("a.png", b"1")) == ("a.png", b"1")
    c.lock()
