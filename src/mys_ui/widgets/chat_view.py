"""Лента сообщений — «журнал» (как в vsc_web, не пузыри).

Раскладка — ``QScrollArea`` с вертикальным стеком виджетов-строк ``MessageRow``.
Так высота строки считается самой раскладкой по реальной ширине (перенос слов
работает корректно), и нет двойного рендера, который был у ``QListWidget`` +
``setItemWidget`` (делегат списка рисовал сырое тело под виджетом).

Совместимость с тестами/потребителями: ``count()`` — число строк, ``item(i)``
возвращает ``MessageRow`` (у него есть ``.text()`` с сырым телом), ``clear()``.

Отправитель различается цветом имени: своё — акцент (кобальт), чужое — обычный
текст, anon — приглушённый. Время берётся из серверного ``created_ts``, иначе из
``sent_at``/``received_at``.
"""

import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QScrollArea,
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
        self.raw_body = body
        self.setObjectName("MessageRow")
        t = theme.tokens()
        self.setStyleSheet(
            f"#MessageRow {{ border-bottom: 1px solid {t['border2']}; }}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 12, 20, 12)
        root.setSpacing(4)

        header = QHBoxLayout()
        header.setSpacing(10)
        name = QLabel(author)
        name.setTextFormat(Qt.PlainText)  # имя от собеседника — не рендерим как HTML
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

    def text(self) -> str:
        """Сырое тело сообщения (для совместимости с тестами на ленту)."""
        return self.raw_body


class ChatView(QScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ChatView")
        self.setWidgetResizable(True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._rows: list[MessageRow] = []
        self._container = QWidget()
        self._container.setObjectName("ChatContainer")
        self._vbox = QVBoxLayout(self._container)
        self._vbox.setContentsMargins(0, 0, 0, 0)
        self._vbox.setSpacing(0)
        self._vbox.addStretch(1)  # строки добавляются перед растяжкой → прижаты вверх
        self.setWidget(self._container)

    # -- совместимый API ----------------------------------------------------

    def count(self) -> int:
        return len(self._rows)

    def item(self, i: int) -> MessageRow:
        return self._rows[i]

    def clear(self) -> None:
        for row in self._rows:
            self._vbox.removeWidget(row)
            row.deleteLater()
        self._rows = []

    # -- наполнение ---------------------------------------------------------

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
            row = MessageRow(
                author=author, author_color=color, when=when,
                body=body, media=m.get("media"),
            )
            # вставляем перед финальной растяжкой
            self._vbox.insertWidget(self._vbox.count() - 1, row)
            self._rows.append(row)
        QTimer.singleShot(0, self._scroll_to_bottom)

    def _scroll_to_bottom(self) -> None:
        bar = self.verticalScrollBar()
        bar.setValue(bar.maximum())
