"""Предпросмотр вложений перед отправкой (перетаскивание, Ctrl+V) — как в Telegram.

Вложение — путь к файлу или картинка из буфера; картинку держим в памяти и
отдаём байтами PNG (во временный файл на диск открытый текст не пишем).
"""

import os

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel

from mys_ui.widgets.brutal import BrutalButton
from mys_ui.windows.frameless import FramelessDialog

_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
_PREVIEW = 360


def image_png(image: QImage) -> bytes:
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.WriteOnly)
    image.save(buf, "PNG")
    return bytes(data)


def _size(n: int) -> str:
    for unit in ("Б", "КБ", "МБ"):
        if n < 1024 or unit == "МБ":
            return f"{n:.0f} {unit}" if unit == "Б" else f"{n:.1f} {unit}"
        n /= 1024
    return ""


class AttachDialog(FramelessDialog):
    """items: list[str | QImage]. Enter — отправить, Esc — отмена."""

    def __init__(self, items: list, parent=None):
        n = len(items)
        super().__init__("Отправить изображение" if n == 1 and _is_image(items[0]) else f"Отправить файлы: {n}", parent)
        self.setMinimumWidth(420)
        for item in items[:10]:
            self.body_layout.addWidget(self._row(item))
        if n > 10:
            self.body_layout.addWidget(QLabel(f"…и ещё {n - 10}"))
        self.body_layout.addSpacing(12)
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = BrutalButton("Отмена", "minimal")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        send = BrutalButton("Отправить", "primary")
        send.clicked.connect(self.accept)
        send.setDefault(True)
        buttons.addWidget(send)
        self.body_layout.addLayout(buttons)
        send.setFocus()

    def _row(self, item) -> QLabel:
        if _is_image(item):
            pix = QPixmap.fromImage(item) if isinstance(item, QImage) else QPixmap(item)
            if not pix.isNull():
                lbl = QLabel()
                lbl.setPixmap(pix.scaled(_PREVIEW, _PREVIEW, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                lbl.setAlignment(Qt.AlignCenter)
                return lbl
        name = os.path.basename(item) if isinstance(item, str) else "изображение.png"
        size = _size(os.path.getsize(item)) if isinstance(item, str) and os.path.exists(item) else ""
        lbl = QLabel(f"📎 {name}" + (f"  ·  {size}" if size else ""))
        lbl.setTextFormat(Qt.PlainText)  # имя файла — не HTML
        return lbl


def _is_image(item) -> bool:
    return isinstance(item, QImage) or os.path.splitext(item)[1].lower() in _IMAGE_EXT
