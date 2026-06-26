"""Строка ввода сообщения: вложение (декоративно) + поле + «Отправить»."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QWidget

from mys_ui.widgets.brutal import BrutalButton, BrutalLineEdit


class MessageInput(QWidget):
    message_submitted = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("InputBar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(12)

        self.btn_attach = BrutalButton("Файл", "default")
        f = self.btn_attach.font()
        f.setPixelSize(20)
        f.setBold(False)
        self.btn_attach.setFont(f)
        self.btn_attach.setToolTip("Вложения недоступны в P2P v1")

        self.field = BrutalLineEdit()
        self.field.setObjectName("MsgField")
        self.field.setPlaceholderText("Сообщение…")

        self.btn_send = BrutalButton("Отправить", "primary")

        layout.addWidget(self.btn_attach)
        layout.addWidget(self.field, 1)
        layout.addWidget(self.btn_send)

        self.btn_send.clicked.connect(self._submit)
        self.field.returnPressed.connect(self._submit)

    def _submit(self) -> None:
        text = self.field.text().strip()
        if not text:
            return
        self.field.clear()
        self.message_submitted.emit(text)
