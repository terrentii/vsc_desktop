"""Аватарка комнаты: картинка с сервера или монограмма в стиле МЫС (квадрат, 2px рамка)."""

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap

from mys_ui import theme


def avatar_pixmap(data: bytes | None, title: str, size: int) -> QPixmap:
    t = theme.tokens()
    out = QPixmap(size, size)
    out.fill(QColor(t["line"]))  # рамка — заливкой, как у кнопок
    p = QPainter(out)
    inner = QRect(2, 2, size - 4, size - 4)
    img = QPixmap()
    if data and img.loadFromData(data):
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.drawPixmap(inner, img.scaled(inner.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
    else:
        p.fillRect(inner, QColor(t["surface"]))
        f = QFont()
        f.setFamilies(["GOST type B", "GOST 2.304 type A", "monospace"])
        f.setBold(True)
        f.setPixelSize(max(10, size // 2))
        p.setFont(f)
        p.setPen(QColor(t["text"]))
        p.drawText(inner, Qt.AlignCenter, (title.strip()[:1] or "#").upper())
    p.end()
    return out
