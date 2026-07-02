"""Тематические замены системных QMessageBox/QInputDialog.

Системные диалоги (Fusion) выбиваются из брутал-стиля DS — здесь их аналоги на
``FramelessDialog`` + ``BrutalButton``: подтверждение, предупреждение, ввод
строки и многострочного текста. API — модальные функции, как у Qt-статиков.
"""

from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPlainTextEdit

from mys_ui.widgets.brutal import BrutalButton, BrutalLineEdit
from mys_ui.windows.frameless import FramelessDialog


class _MessageDialog(FramelessDialog):
    def __init__(self, title: str, text: str, *, ok_label: str, cancel_label: str | None,
                 danger: bool = False, parent=None):
        super().__init__(title, parent)
        self.setMinimumWidth(420)

        lbl = QLabel(text)
        lbl.setWordWrap(True)
        self.body_layout.addWidget(lbl)
        self.body_layout.addSpacing(12)

        buttons = QHBoxLayout()
        buttons.addStretch()
        if cancel_label is not None:
            btn_cancel = BrutalButton(cancel_label, "minimal")
            btn_cancel.clicked.connect(self.reject)
            buttons.addWidget(btn_cancel)
        btn_ok = BrutalButton(ok_label, "danger" if danger else "primary")
        btn_ok.clicked.connect(self.accept)
        buttons.addWidget(btn_ok)
        self.body_layout.addLayout(buttons)
        btn_ok.setFocus()


def confirm(parent, title: str, text: str, *, ok_label: str = "Да",
            danger: bool = False) -> bool:
    """Вопрос с «Отмена» / подтверждением. True — подтверждено."""
    dlg = _MessageDialog(title, text, ok_label=ok_label, cancel_label="Отмена",
                         danger=danger, parent=parent)
    return dlg.exec() == QDialog.Accepted


def warn(parent, title: str, text: str) -> None:
    """Предупреждение с одной кнопкой «Понятно» (замена QMessageBox.warning)."""
    _MessageDialog(title, text, ok_label="Понятно", cancel_label=None,
                   parent=parent).exec()


class _TextDialog(FramelessDialog):
    def __init__(self, title: str, label: str, text: str = "", *,
                 multiline: bool = False, ok_label: str = "Сохранить", parent=None):
        super().__init__(title, parent)
        self.setMinimumWidth(470)

        lbl = QLabel(label)
        lbl.setObjectName("FieldLabel")
        self.body_layout.addWidget(lbl)
        if multiline:
            self.field = QPlainTextEdit()
            self.field.setObjectName("DialogTextArea")
            self.field.setPlainText(text)
            self.field.setMinimumHeight(120)
        else:
            self.field = BrutalLineEdit()
            self.field.setText(text)
            self.field.returnPressed.connect(self.accept)
        self.body_layout.addWidget(self.field)
        self.body_layout.addSpacing(12)

        buttons = QHBoxLayout()
        buttons.addStretch()
        btn_cancel = BrutalButton("Отмена", "minimal")
        btn_cancel.clicked.connect(self.reject)
        buttons.addWidget(btn_cancel)
        btn_ok = BrutalButton(ok_label, "primary")
        btn_ok.clicked.connect(self.accept)
        buttons.addWidget(btn_ok)
        self.body_layout.addLayout(buttons)
        self.field.setFocus()

    def value(self) -> str:
        if isinstance(self.field, QPlainTextEdit):
            return self.field.toPlainText()
        return self.field.text()


def ask_text(parent, title: str, label: str, text: str = "", *,
             ok_label: str = "Создать") -> tuple[str, bool]:
    """Однострочный ввод (замена QInputDialog.getText). → (текст, ok)."""
    dlg = _TextDialog(title, label, text, ok_label=ok_label, parent=parent)
    ok = dlg.exec() == QDialog.Accepted
    return dlg.value(), ok


def ask_multiline(parent, title: str, label: str, text: str = "") -> tuple[str, bool]:
    """Многострочный ввод (замена QInputDialog.getMultiLineText). → (текст, ok)."""
    dlg = _TextDialog(title, label, text, multiline=True, parent=parent)
    ok = dlg.exec() == QDialog.Accepted
    return dlg.value(), ok
