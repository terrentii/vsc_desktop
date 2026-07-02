"""Строка ввода сообщения: плашка ответа + вложение + поле + «Отправить»."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget

from mys_ui.widgets.brutal import BrutalButton, BrutalLineEdit


class MessageInput(QWidget):
    message_submitted = Signal(str)
    file_submitted = Signal(str)  # путь к выбранному файлу; чтение — в MainWindow
    reply_cancelled = Signal()    # пользователь снял режим «ответ на…»

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("InputBar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 8, 16, 12)
        outer.setSpacing(6)

        # Плашка «↩ Ответ <автор>: <текст>» + крестик отмены (скрыта по умолчанию)
        self._reply_bar = QWidget()
        self._reply_bar.setObjectName("ReplyBar")
        rb = QHBoxLayout(self._reply_bar)
        rb.setContentsMargins(4, 0, 0, 0)
        rb.setSpacing(8)
        self._reply_label = QLabel("")
        self._reply_label.setObjectName("ReplyLabel")
        rb.addWidget(self._reply_label, 1)
        self._reply_close = QToolButton()
        self._reply_close.setObjectName("ReplyClose")
        self._reply_close.setText("✕")
        self._reply_close.setToolTip("Отменить ответ")
        self._reply_close.setCursor(Qt.PointingHandCursor)
        self._reply_close.clicked.connect(self.clear_reply)
        rb.addWidget(self._reply_close, 0)
        self._reply_bar.hide()
        outer.addWidget(self._reply_bar)

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self.btn_attach = BrutalButton("Файл", "default")
        f = self.btn_attach.font()
        f.setPixelSize(20)
        f.setBold(False)
        self.btn_attach.setFont(f)
        self.btn_attach.setToolTip("Отправить файл")

        self.field = BrutalLineEdit()
        self.field.setObjectName("MsgField")
        self.field.setPlaceholderText("Сообщение…")

        self.btn_send = BrutalButton("Отправить", "primary")

        layout.addWidget(self.btn_attach)
        layout.addWidget(self.field, 1)
        layout.addWidget(self.btn_send)
        outer.addLayout(layout)

        self.btn_send.clicked.connect(self._submit)
        self.field.returnPressed.connect(self._submit)
        self.btn_attach.clicked.connect(self._pick_file)

    # -- режим «ответ на…» ---------------------------------------------------

    def set_reply(self, author: str, snippet: str) -> None:
        text = f"↩ Ответ {author}"
        if snippet:
            text += f": {snippet}"
        self._reply_label.setText(text)
        self._reply_bar.show()
        self.field.setFocus()

    def clear_reply(self) -> None:
        if self._reply_bar.isVisible():
            self._reply_bar.hide()
            self._reply_label.setText("")
            self.reply_cancelled.emit()

    # -- отправка --------------------------------------------------------------

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
