"""Строка ввода сообщения: плашка ответа + вложение + поле + «Отправить».

Поведение как в Telegram Desktop: Enter — отправить, Shift+Enter — новая строка,
Esc — отменить ответ (в пустом поле без ответа — закрыть чат), ↑ в пустом поле —
изменить своё последнее сообщение, Ctrl+V с картинкой или файлами и перетаскивание
файлов в поле — вложения (с предпросмотром в MainWindow).
"""

from PySide6.QtCore import QEvent, QRect, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from mys_ui import theme
from mys_ui.widgets.brutal import CONTROL_H, BrutalButton

_MAX_LINES = 6
_SHADOW = 4


def local_paths(mime) -> list[str]:
    """Локальные файлы из перетаскивания/буфера (ссылки на веб не берём)."""
    if not mime.hasUrls():
        return []
    return [u.toLocalFile() for u in mime.urls() if u.isLocalFile() and u.toLocalFile()]


class ComposeEdit(QPlainTextEdit):
    """Многострочное поле: растёт до 6 строк, клавиши и вставка — сигналами."""

    submit = Signal()
    escape = Signal()
    edit_last = Signal()
    files_dropped = Signal(list)    # пути к файлам
    image_pasted = Signal(QImage)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("MsgField")
        self.setTabChangesFocus(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.document().setDocumentMargin(0)
        self.textChanged.connect(self._fit)
        self._fit()

    # совместимость с прежним QLineEdit-полем
    def text(self) -> str:
        return self.toPlainText()

    def setText(self, text: str) -> None:
        self.setPlainText(text)
        self.moveCursor(self.textCursor().MoveOperation.End)

    def _fit(self) -> None:
        """Высота по числу строк (не больше 6), одна строка — как у кнопок."""
        line = self.fontMetrics().lineSpacing()
        total = max(1, int(self.document().size().height()))
        lines = min(_MAX_LINES, total)
        # прокрутка — только когда строк больше, чем помещается
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded if total > _MAX_LINES else Qt.ScrollBarAlwaysOff)
        # рамка 2+2, отступы 7+7 (theme.py: QPlainTextEdit#MsgField) и запас под курсор
        self.setFixedHeight(max(CONTROL_H - _SHADOW, lines * line + 22))

    def keyPressEvent(self, e) -> None:
        key, mods = e.key(), e.modifiers()
        if key in (Qt.Key_Return, Qt.Key_Enter) and not (mods & Qt.ShiftModifier):
            self.submit.emit()
            return
        if key == Qt.Key_Escape:
            self.escape.emit()
            return
        if key == Qt.Key_Up and not self.toPlainText() and not mods:
            self.edit_last.emit()
            return
        super().keyPressEvent(e)

    def canInsertFromMimeData(self, source) -> bool:
        return source.hasImage() or bool(local_paths(source)) or super().canInsertFromMimeData(source)

    def insertFromMimeData(self, source) -> None:
        paths = local_paths(source)
        if paths:
            self.files_dropped.emit(paths)
        elif source.hasImage():
            image = QImage(source.imageData())
            if not image.isNull():
                self.image_pasted.emit(image)
        elif source.hasText():
            self.insertPlainText(source.text())  # только текст: чужое оформление не тащим


class _ShadowBox(QWidget):
    """Подложка с блочной тенью (как у BrutalLineEdit): серая, на фокусе — кобальт."""

    def __init__(self, child: QWidget, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, _SHADOW, _SHADOW)
        lay.addWidget(child)
        self._child = child
        child.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.FocusIn, QEvent.FocusOut):
            self.update()
        return False

    def paintEvent(self, e):
        t = theme.tokens()
        p = QPainter(self)
        color = t["accent"] if self._child.hasFocus() else t["border2"]
        p.fillRect(QRect(_SHADOW, _SHADOW, self.width() - _SHADOW, self.height() - _SHADOW), QColor(color))
        p.end()


class MessageInput(QWidget):
    message_submitted = Signal(str)
    file_submitted = Signal(str)       # путь к выбранному файлу; чтение — в MainWindow
    files_submitted = Signal(list)     # перетащили / вставили файлы — предпросмотр в MainWindow
    image_pasted = Signal(QImage)      # Ctrl+V с картинкой
    reply_cancelled = Signal()         # пользователь снял режим «ответ на…»
    close_requested = Signal()         # Esc в пустом поле без ответа
    edit_last_requested = Signal()     # ↑ в пустом поле
    text_edited = Signal(str)          # пользователь печатает (для «печатает…»)

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
        self._reply_label.setTextFormat(Qt.PlainText)  # цитата собеседника — не HTML
        self._reply_label.setObjectName("ReplyLabel")
        rb.addWidget(self._reply_label, 1)
        self._reply_close = QToolButton()
        self._reply_close.setObjectName("ReplyClose")
        self._reply_close.setText("✕")
        self._reply_close.setToolTip("Отменить ответ (Esc)")
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
        self.btn_attach.setToolTip("Отправить файл — или перетащите его в окно, или вставьте Ctrl+V")

        self.field = ComposeEdit()
        self.field.setPlaceholderText("Сообщение…")
        self._programmatic = False

        self.btn_send = BrutalButton("Отправить", "primary")

        layout.addWidget(self.btn_attach, 0, Qt.AlignBottom)
        layout.addWidget(_ShadowBox(self.field), 1)
        layout.addWidget(self.btn_send, 0, Qt.AlignBottom)
        outer.addLayout(layout)

        self.btn_send.clicked.connect(self._submit)
        self.field.submit.connect(self._submit)
        self.field.escape.connect(self._on_escape)
        self.field.edit_last.connect(self.edit_last_requested)
        self.field.files_dropped.connect(self.files_submitted)
        self.field.image_pasted.connect(self.image_pasted)
        self.field.textChanged.connect(self._on_changed)
        self.btn_attach.clicked.connect(self._pick_file)

    # -- текст и черновики ----------------------------------------------------

    def text(self) -> str:
        return self.field.toPlainText()

    def set_text(self, text: str) -> None:
        """Подставить текст (черновик) без сигнала «печатает»."""
        self._programmatic = True
        try:
            self.field.setText(text)
        finally:
            self._programmatic = False

    def _on_changed(self) -> None:
        if not self._programmatic and self.field.toPlainText():
            self.text_edited.emit(self.field.toPlainText())

    # -- режим «ответ на…» ---------------------------------------------------

    def set_reply(self, author: str, snippet: str) -> None:
        text = f"↩ Ответ {author}"
        if snippet:
            text += f": {snippet}"
        self._reply_label.setText(text)
        self._reply_bar.show()
        self.field.setFocus()

    def clear_reply(self) -> None:
        if not self._reply_bar.isHidden():
            self._reply_bar.hide()
            self._reply_label.setText("")
            self.reply_cancelled.emit()

    def _on_escape(self) -> None:
        if not self._reply_bar.isHidden():
            self.clear_reply()
        elif not self.field.toPlainText().strip():
            self.close_requested.emit()

    # -- отправка --------------------------------------------------------------

    def _submit(self) -> None:
        text = self.field.toPlainText().strip()
        if not text:
            return
        self.set_text("")
        self.message_submitted.emit(text)

    def _pick_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Выбрать файл")
        if path:
            self.file_submitted.emit(path)
