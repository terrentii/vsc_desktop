"""Строка ввода сообщения: вложение + поле + «Отправить»."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QWidget

from mys_ui.widgets.brutal import BrutalButton, BrutalLineEdit


class MessageInput(QWidget):
    message_submitted = Signal(str)
    file_submitted = Signal(str)  # путь к выбранному файлу; чтение — в MainWindow

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
        self.btn_attach.setToolTip("Отправить файл (доступно в P2P-режиме)")

        self.field = BrutalLineEdit()
        self.field.setObjectName("MsgField")
        self.field.setPlaceholderText("Сообщение…")

        self.btn_send = BrutalButton("Отправить", "primary")

        layout.addWidget(self.btn_attach)
        layout.addWidget(self.field, 1)
        layout.addWidget(self.btn_send)

        self.btn_send.clicked.connect(self._submit)
        self.field.returnPressed.connect(self._submit)
        self.btn_attach.clicked.connect(self._pick_file)

    def _submit(self) -> None:
        text = self.field.text().strip()
        if not text:
            return
        self.field.clear()
        self.message_submitted.emit(text)

    def _pick_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Выбрать файл")
        if path:
            self.file_submitted.emit(path)
