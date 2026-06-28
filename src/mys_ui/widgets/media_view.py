"""Рендер вложения по локальной ссылке: картинка ≤320×280 или плашка-файл.

Источник файлов (скачивание из «Центра», приём по P2P) — под-проекты B/C.
"""

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from mys_ui import theme

_IMG_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


class MediaView(QWidget):
    def __init__(self, ref: str, parent=None):
        super().__init__(parent)
        self._ref = ref
        t = theme.tokens()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 6, 0, 0)

        ext = os.path.splitext(ref)[1].lower()
        self.is_image = ext in _IMG_EXT
        if self.is_image:
            self.image = QLabel()
            pm = QPixmap(ref)
            if not pm.isNull():
                pm = pm.scaled(320, 280, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.image.setPixmap(pm)
            self.image.setStyleSheet(f"border: 1px solid {t['line']};")
            root.addWidget(self.image)
        else:
            name = os.path.basename(ref)
            self.link = QLabel(f"📎 {name}")
            self.link.setStyleSheet(
                f"color: {t['text']}; border: 1px solid {t['line']};"
                " padding: 8px 14px; font-family: monospace; font-size: 11px;"
            )
            root.addWidget(self.link)
