"""Лента сообщений — «журнал» (как в vsc_web, не пузыри).

Остаётся ``QListWidget`` (UI-тесты опираются на ``count()`` и ``item(i).text()``):
``item.text()`` хранит сырое тело, но каждая строка рисуется виджетом
``MessageRow`` через ``setItemWidget`` — это нужно для интерактивных блоков кода
(кнопка «Копировать») и медиа.

Отправитель различается цветом имени: своё — акцент (кобальт), чужое — обычный
текст, anon — приглушённый mono. Время берётся из серверного ``created_ts``,
иначе из ``sent_at``/``received_at``.
"""

import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mys_ui import theme
from mys_ui.widgets.code_block import CodeBlock
from mys_ui.widgets.media_view import MediaView
from mys_ui.widgets.message_text import split_segments


def _fmt_time(epoch) -> str:
    if not epoch:
        return ""
    try:
        return time.strftime("%H:%M", time.localtime(float(epoch)))
    except (TypeError, ValueError):
        return ""


class MessageRow(QWidget):
    def __init__(self, *, author, author_color, when, body, media=None, parent=None):
        super().__init__(parent)
        self.author = author
        self.author_color = author_color
        self.when = when
        t = theme.tokens()

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 12, 20, 12)
        root.setSpacing(4)

        header = QHBoxLayout()
        header.setSpacing(10)
        name = QLabel(author)
        name.setTextFormat(Qt.PlainText)  # имя от удалённого собеседника — не рендерим как HTML
        nf = QFont()
        nf.setBold(True)
        nf.setPixelSize(13)
        name.setFont(nf)
        name.setStyleSheet(f"color: {author_color};")
        header.addWidget(name)
        if when:
            time_lbl = QLabel(when)
            time_lbl.setStyleSheet(
                f"color: {t['text3']}; font-family: monospace; font-size: 10px;"
            )
            header.addWidget(time_lbl)
        header.addStretch()
        root.addLayout(header)

        for kind, seg in split_segments(body):
            if kind == "code":
                root.addWidget(CodeBlock(seg))
            else:
                lbl = QLabel(seg)
                lbl.setTextFormat(Qt.PlainText)  # тело от собеседника — не рендерим как HTML
                lbl.setWordWrap(True)
                lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
                lbl.setStyleSheet(f"color: {t['text']}; font-size: 14px;")
                root.addWidget(lbl)

        if media:
            root.addWidget(MediaView(media))


class ChatView(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ChatView")
        self.setSelectionMode(QListWidget.NoSelection)
        self.setFocusPolicy(Qt.NoFocus)
        self.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.setUniformItemSizes(False)
        self.setSpacing(0)
        self.setWordWrap(True)

    def show_messages(self, messages: list[dict], *, peer_label: str = "Собеседник") -> None:
        self.clear()
        t = theme.tokens()
        for m in messages:
            body = m["body"].decode("utf-8", "replace") if m["body"] is not None else ""
            own = m["direction"] == "out"
            if own:
                author = "я"
                color = t["accent"]
            else:
                author = m.get("author") or peer_label
                color = t["text3"] if str(author).startswith("Anon") else t["text"]
            when = _fmt_time(
                m.get("created_ts") or m.get("sent_at") or m.get("received_at")
            )
            item = QListWidgetItem(body)
            row = MessageRow(
                author=author, author_color=color, when=when,
                body=body, media=m.get("media"),
            )
            item.setSizeHint(row.sizeHint())
            self.addItem(item)
            self.setItemWidget(item, row)
        self.scrollToBottom()
