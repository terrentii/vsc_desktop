"""Лента сообщений — «строки журнала» (новейший дизайн DS, не пузыри).

Каждое сообщение: слева квадрат-аватар (mono-инициалы; своё — кобальтовое),
сверху имя + mono-время, ниже чистый текст без коробки; строки разделяются
hairline-линией. Остаётся ``QListWidget`` (UI-тесты опираются на ``count()`` и
``item(i).text()``), но рисуется делегатом. Тело — ``DisplayRole``; направление,
время, автор и инициалы — в доп. ролях.

Spec: preview/components-message.html («убраны 2010-е скруглённые пузыри»).
"""

import time

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPen
from PySide6.QtWidgets import (
    QFileDialog,
    QListWidget,
    QListWidgetItem,
    QStyledItemDelegate,
)

from mys_ui import theme

_DIRECTION_ROLE = Qt.UserRole + 1
_TIME_ROLE = Qt.UserRole + 2
_AUTHOR_ROLE = Qt.UserRole + 3
_AVATAR_ROLE = Qt.UserRole + 4
_FILE_BODY_ROLE = Qt.UserRole + 5
_FILENAME_ROLE = Qt.UserRole + 6

_PAD_L = 20
_PAD_R = 20
_PAD_Y = 12
_AVATAR = 32
_GAP = 12
_NAME_GAP = 4


def _name_font() -> QFont:
    f = QFont()
    f.setFamilies(["GOST type B", "GOST 2.304 type A", "sans-serif"])
    f.setPixelSize(16)
    f.setWeight(QFont.DemiBold)
    return f


def _body_font() -> QFont:
    f = QFont()
    f.setFamilies(["GOST type B", "GOST 2.304 type A", "sans-serif"])
    f.setPixelSize(16)
    return f


class _JournalDelegate(QStyledItemDelegate):
    def _content_x(self) -> int:
        return _PAD_L + _AVATAR + _GAP

    def _body_geom(self, option, index):
        body = index.data(Qt.DisplayRole) or ""
        cx = self._content_x()
        cw = max(60, option.rect.width() - cx - _PAD_R)
        from PySide6.QtGui import QFontMetrics

        name_h = QFontMetrics(_name_font()).height()
        bf = QFontMetrics(_body_font())
        flags = int(Qt.TextWordWrap)
        bh = bf.boundingRect(QRect(0, 0, cw, 100000), flags, body).height()
        return cx, cw, name_h, bh, body, flags

    def sizeHint(self, option, index):
        _, _, name_h, bh, _, _ = self._body_geom(option, index)
        h = _PAD_Y + name_h + _NAME_GAP + bh + _PAD_Y
        return QSize(option.rect.width(), max(h, _PAD_Y * 2 + _AVATAR))

    def paint(self, painter, option, index):
        t = theme.tokens()
        own = index.data(_DIRECTION_ROLE) == "out"
        author = index.data(_AUTHOR_ROLE) or ("я" if own else "Собеседник")
        when = index.data(_TIME_ROLE) or ""
        avatar = index.data(_AVATAR_ROLE) or author[:2]
        cx, cw, name_h, bh, body, flags = self._body_geom(option, index)
        r = option.rect

        painter.save()
        painter.setRenderHint(painter.RenderHint.Antialiasing, False)

        # hairline-разделитель сверху (кроме первой строки)
        if index.row() > 0:
            painter.setPen(QPen(QColor(t["border2"]), 1))
            painter.drawLine(r.left() + _PAD_L, r.top(), r.right() - _PAD_R, r.top())

        top = r.top() + _PAD_Y

        # аватар-квадрат
        av = QRect(r.left() + _PAD_L, top, _AVATAR, _AVATAR)
        painter.fillRect(av, QColor(t["accent"] if own else t["line"]))
        af = QFont()
        af.setFamilies(["GOST type B", "GOST 2.304 type A", "monospace"])
        af.setBold(True)
        af.setPixelSize(13)
        painter.setFont(af)
        painter.setPen(QColor("#ffffff") if own else QColor(t["bg"]))
        painter.drawText(av, Qt.AlignCenter, avatar)

        # имя + время (baseline)
        x = r.left() + cx
        nf = _name_font()
        painter.setFont(nf)
        painter.setPen(QColor(t["text"]))
        from PySide6.QtGui import QFontMetrics

        nm = QFontMetrics(nf)
        painter.drawText(QRect(x, top, cw, name_h), Qt.AlignVCenter | Qt.AlignLeft, author)
        if when:
            tf = QFont()
            tf.setFamilies(["GOST type B", "GOST 2.304 type A", "monospace"])
            tf.setPixelSize(11)
            painter.setFont(tf)
            painter.setPen(QColor(t["text3"]))
            aw = nm.horizontalAdvance(author) + 10
            painter.drawText(
                QRect(x + aw, top, cw - aw, name_h), Qt.AlignVCenter | Qt.AlignLeft, when
            )

        # тело
        painter.setFont(_body_font())
        painter.setPen(QColor(t["text"]))
        painter.drawText(QRect(x, top + name_h + _NAME_GAP, cw, bh), flags, body)
        painter.restore()


def _fmt_time(epoch) -> str:
    if not epoch:
        return ""
    try:
        return time.strftime("%H:%M", time.localtime(float(epoch)))
    except (TypeError, ValueError):
        return ""


def _fmt_size(n: int) -> str:
    if n >= 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} МБ"
    if n >= 1024:
        return f"{n / 1024:.0f} КБ"
    return f"{n} Б"


def _display_text(m: dict) -> str:
    if m.get("kind") == "file":
        size = len(m["body"]) if m["body"] is not None else 0
        return f"📎 {m.get('filename') or 'файл'} ({_fmt_size(size)})"
    return m["body"].decode("utf-8", "replace") if m["body"] is not None else ""


def _avatar_for(author: str, own: bool) -> str:
    if own:
        return "я"
    a = author.strip()
    if not a:
        return "?"
    parts = a.split()
    if len(parts) >= 2:
        return (parts[0][:1] + parts[1][:1]).upper()
    return a[:2].lower()


class ChatView(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ChatView")
        self.setItemDelegate(_JournalDelegate(self))
        self.setSelectionMode(QListWidget.NoSelection)
        self.setFocusPolicy(Qt.NoFocus)
        self.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.setUniformItemSizes(False)
        self.setSpacing(0)
        self.setWordWrap(True)
        self.itemDoubleClicked.connect(self._on_double_click)

    def show_messages(self, messages: list[dict], *, peer_label: str = "Собеседник") -> None:
        self.clear()
        for m in messages:
            own = m["direction"] == "out"
            author = "я" if own else (m.get("sender") or peer_label)
            item = QListWidgetItem(_display_text(m))
            item.setData(_DIRECTION_ROLE, m["direction"])
            item.setData(_AUTHOR_ROLE, author)
            item.setData(_TIME_ROLE, _fmt_time(m.get("sent_at") or m.get("received_at")))
            item.setData(_AVATAR_ROLE, _avatar_for(author, own))
            if m.get("kind") == "file":
                item.setData(_FILE_BODY_ROLE, m["body"])
                item.setData(_FILENAME_ROLE, m.get("filename"))
            self.addItem(item)
        self.scrollToBottom()

    def _on_double_click(self, item: QListWidgetItem) -> None:
        body = item.data(_FILE_BODY_ROLE)
        if body is None:
            return
        filename = item.data(_FILENAME_ROLE) or "файл"
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить файл", filename)
        if not path:
            return
        with open(path, "wb") as fh:
            fh.write(body)
