"""Лента сообщений диалога.

Остаётся ``QListWidget`` (UI-тесты опираются на ``count()``/``item(i).text()``),
но рисуется делегатом в стиле дизайна: «свои» — акцентный пузырь справа с блочной
тенью, «входящие» — пузырь слева. Текст элемента = тело сообщения; направление
хранится в ``Qt.UserRole``.
"""

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPen
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QStyledItemDelegate

from mys_ui import theme

_DIRECTION_ROLE = Qt.UserRole + 1

_PAD_X = 13
_PAD_Y = 9
_SHADOW = 3
_MARGIN = 6
_MAX_FRAC = 0.74


class _BubbleDelegate(QStyledItemDelegate):
    def _layout(self, option, index):
        """Геометрия пузыря: (own, text_rect, bubble_rect) в координатах элемента."""
        own = index.data(_DIRECTION_ROLE) == "out"
        text = index.data(Qt.DisplayRole) or ""
        avail = option.rect.width() - 2 * _MARGIN - _SHADOW
        max_w = max(120, int(avail * _MAX_FRAC))
        fm = option.fontMetrics
        flags = int(Qt.TextWordWrap)
        inner = max_w - 2 * _PAD_X
        bound = fm.boundingRect(QRect(0, 0, inner, 10000), flags, text)
        bw = min(max_w, bound.width() + 2 * _PAD_X)
        bh = bound.height() + 2 * _PAD_Y
        top = option.rect.top() + _MARGIN
        if own:
            left = option.rect.right() - _MARGIN - _SHADOW - bw
        else:
            left = option.rect.left() + _MARGIN
        bubble = QRect(left, top, bw, bh)
        text_rect = bubble.adjusted(_PAD_X, _PAD_Y, -_PAD_X, -_PAD_Y)
        return own, text_rect, bubble, text, flags

    def sizeHint(self, option, index):
        self.initStyleOption(option, index)
        _, _, bubble, _, _ = self._layout(option, index)
        return QSize(option.rect.width(), bubble.height() + 2 * _MARGIN)

    def paint(self, painter, option, index):
        self.initStyleOption(option, index)
        own, text_rect, bubble, text, flags = self._layout(option, index)
        t = theme.tokens()
        line = QColor(t["line"])

        painter.save()
        painter.setRenderHint(painter.RenderHint.Antialiasing, False)

        # блочная тень (смещённый прямоугольник)
        shadow = bubble.translated(-_SHADOW if own else _SHADOW, _SHADOW)
        painter.fillRect(shadow, line)

        if own:
            fill, fg = QColor(t["accent"]), QColor("#ffffff")
        else:
            fill, fg = QColor(t["bubbleThem"]), QColor(t["bubbleThemText"])
        painter.fillRect(bubble, fill)
        painter.setPen(QPen(line, 1))
        painter.drawRect(bubble.adjusted(0, 0, -1, -1))

        painter.setPen(fg)
        painter.drawText(text_rect, flags, text)
        painter.restore()


class ChatView(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ChatView")
        self.setItemDelegate(_BubbleDelegate(self))
        self.setSelectionMode(QListWidget.NoSelection)
        self.setFocusPolicy(Qt.NoFocus)
        self.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.setUniformItemSizes(False)
        self.setSpacing(0)
        self.setWordWrap(True)

    def show_messages(self, messages: list[dict]) -> None:
        self.clear()
        for m in messages:
            body = m["body"].decode("utf-8", "replace") if m["body"] is not None else ""
            item = QListWidgetItem(body)
            item.setData(_DIRECTION_ROLE, m["direction"])
            item.setFont(QFont())
            self.addItem(item)
        self.scrollToBottom()
