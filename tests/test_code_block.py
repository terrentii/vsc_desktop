from PySide6.QtWidgets import QApplication

from mys_ui.widgets.code_block import CodeBlock


def test_code_block_shows_code_and_copies(qtbot):
    cb = CodeBlock("x = 1\ny = 2")
    qtbot.addWidget(cb)
    assert cb.pre.toPlainText() == "x = 1\ny = 2"
    cb._copy()
    assert QApplication.clipboard().text() == "x = 1\ny = 2"
