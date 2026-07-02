"""Лента сообщений — «строки журнала», отображение в паритете с веб-версией.

Каждое сообщение (как на soufos.ru, см. ``vsc_web``): имя автора жирным
(своё — кобальтом), рядом mono-время в веб-формате («сегодня 15:27» /
«вчера 15:27» / «13 май 15:27»), ниже содержимое; строки разделяются
hairline-линией. Аватаров нет — их нет и в вебе.
Содержимое бывает трёх видов:
  - обычный текст, где ```код``` -фенсы рисуются веб-блоком кода: шапка
    «//// CODE» + кнопка «КОПИРОВАТЬ», ниже моно-текст на фоне
    (авто-детект на момент отрисовки, паритет с веб-версией — см.
    ``vsc_web/app.py``'s ``render_text`` — язык после фенса не отрезается,
    это её осознанная особенность, повторяем для паритета);
  - изображение (``kind == "image"``) — инлайн-превью в тонкой рамке, если
    байты уже докачаны (см. ``mys_centralized.sync.fetch_media``), иначе
    плейсхолдер;
  - файл (``kind == "file"``) — иконка-скрепка с именем/размером, либо
    приглашение докачать, если тело ещё не докачано (ленивая докачка вложений
    «Центра»).

Остаётся ``QListWidget`` (UI-тесты опираются на ``count()`` и ``item(i).text()``),
но рисуется делегатом. Тело — ``DisplayRole``; направление, время, автор,
вид и картинка — в доп. ролях.

Spec: preview/components-message.html («убраны 2010-е скруглённые пузыри»).
"""

import datetime as _dt
import re
import time

from PySide6.QtCore import QEvent, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QPixmap, QPen
from PySide6.QtWidgets import (
    QFileDialog,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QStyledItemDelegate,
)

from mys_ui import theme

_DIRECTION_ROLE = Qt.UserRole + 1
_TIME_ROLE = Qt.UserRole + 2
_AUTHOR_ROLE = Qt.UserRole + 3
_FILE_BODY_ROLE = Qt.UserRole + 5
_FILENAME_ROLE = Qt.UserRole + 6
_KIND_ROLE = Qt.UserRole + 7
_IMAGE_ROLE = Qt.UserRole + 8
_MESSAGE_ID_ROLE = Qt.UserRole + 9
_WIRE_ROLE = Qt.UserRole + 10          # серверный id (нужен для «Ответить»)
_REPLY_AUTHOR_ROLE = Qt.UserRole + 11  # цитата: автор
_REPLY_SNIPPET_ROLE = Qt.UserRole + 12  # цитата: первые символы текста
_STATUS_ROLE = Qt.UserRole + 13        # status строки (pending/failed → пометка)

_PAD_L = 26
_PAD_R = 26
_PAD_Y = 16
_NAME_GAP = 8

_CODE_PAD = 13      # внутренний отступ моно-текста в блоке кода
_CODE_HEAD = 36     # высота шапки «//// CODE … КОПИРОВАТЬ»
_SEG_GAP = 10       # промежуток между сегментами текст/код
_MAX_IMAGE_H = 420  # максимальная высота инлайн-превью изображения
_BTN_PAD_X = 14     # горизонтальный внутр. отступ кнопок (вкл. 2px рамку)
_BTN_PAD_Y = 6      # вертикальный внутр. отступ кнопок (вкл. 2px рамку)

_CODE_FENCE_RE = re.compile(r"```([\s\S]*?)```")

_MONTHS = ["янв", "фев", "мар", "апр", "май", "июн",
           "июл", "авг", "сен", "окт", "ноя", "дек"]


def _split_segments(text: str) -> list[tuple[bool, str]]:
    """Разбить текст на чередующиеся (is_code, text) сегменты по ```фенсам```.

    Незакрытый фенс не считается кодом (``re`` без совпадения просто не
    разобьёт текст). Пустой список фенсов -> один нейтральный сегмент."""
    segments: list[tuple[bool, str]] = []
    pos = 0
    for m in _CODE_FENCE_RE.finditer(text):
        if m.start() > pos:
            segments.append((False, text[pos:m.start()]))
        segments.append((True, m.group(1)))
        pos = m.end()
    if pos < len(text):
        segments.append((False, text[pos:]))
    return segments or [(False, text)]


def _name_font() -> QFont:
    f = QFont()
    f.setFamilies(["GOST type B", "GOST 2.304 type A", "sans-serif"])
    f.setPixelSize(21)
    f.setWeight(QFont.Bold)
    return f


def _body_font() -> QFont:
    f = QFont()
    f.setFamilies(["GOST type B", "GOST 2.304 type A", "sans-serif"])
    f.setPixelSize(21)
    return f


def _mono_font() -> QFont:
    f = QFont()
    f.setFamilies(["GOST type B", "GOST 2.304 type A", "monospace"])
    f.setPixelSize(19)
    return f


def _small_mono_font() -> QFont:
    f = QFont()
    f.setFamilies(["GOST type B", "GOST 2.304 type A", "monospace"])
    f.setPixelSize(14)
    return f


_BTN_SHADOW = 3  # смещение блок-тени кнопок (small-вариант BrutalButton)


def _btn_font() -> QFont:
    # тот же язык, что у BrutalButton(small=True): жирный mono-капс
    f = QFont()
    f.setFamilies(["GOST type B", "GOST 2.304 type A", "monospace"])
    f.setBold(True)
    f.setPixelSize(12)
    f.setCapitalization(QFont.AllUppercase)
    f.setLetterSpacing(QFont.PercentageSpacing, 109)
    return f


def _paint_button(painter, rect: QRect, label: str, t: dict, *,
                  accent: bool = False, pressed: bool = False) -> None:
    """Кнопка в точности как BrutalButton: 2px рамка заливкой + блок-тень.

    Никаких 1px-штрихов: рамка — это заливка лица цветом ``line`` с внутренней
    вставкой (у primary лицо кобальтовое). ``pressed`` — лицо наезжает на тень."""
    s = _BTN_SHADOW
    fd = s if pressed else 0
    fw, fh = rect.width() - s, rect.height() - s
    x, y = rect.left(), rect.top()
    if fd < s:
        painter.fillRect(QRect(x + s, y + s, fw, fh), QColor(t["line"]))
    face = QRect(x + fd, y + fd, fw, fh)
    # 2px рамка заливкой; у кобальтовой кнопки — чернильная (ink), как у
    # «Отправить»: белая сливалась бы с тенью, без рамки — с фоном
    painter.fillRect(face, QColor(t["ink"] if accent else t["line"]))
    inner = face.adjusted(2, 2, -2, -2)
    painter.fillRect(inner, QColor(t["accent"] if accent else t["surface"]))
    painter.setFont(_btn_font())
    painter.setPen(QColor("#ffffff" if accent else t["text"]))
    painter.drawText(face, Qt.AlignCenter, label)


class _JournalDelegate(QStyledItemDelegate):
    """Рисует строку журнала; parent — сам ChatView (нужен для сигналов действий)."""

    def __init__(self, view):
        super().__init__(view)
        self._view = view

    def _actions_for(self, index) -> list[str]:
        """Действия строки («ОТВЕТИТЬ» всем; «ИЗМЕНИТЬ»/«УДАЛИТЬ» своим).

        Только когда включены у view (режим «Центр» с сессией), сообщение
        подтверждено сервером (есть wire-id) и строка под курсором —
        как в вебе, кнопки видны лишь у наведённого сообщения."""
        if not getattr(self._view, "actions_enabled", False):
            return []
        if index.row() != getattr(self._view, "_hover_row", -1):
            return []
        if index.data(_WIRE_ROLE) is None:
            return []
        actions = ["ОТВЕТИТЬ"]
        if index.data(_DIRECTION_ROLE) == "out" and index.data(_KIND_ROLE) == "text":
            actions += ["ИЗМЕНИТЬ", "УДАЛИТЬ"]
        elif index.data(_DIRECTION_ROLE) == "out":
            actions += ["УДАЛИТЬ"]  # вложения: тело не редактируется
        return actions

    def _action_rects(self, option, index) -> list[tuple[QRect, str]]:
        """Кликабельные зоны действий в строке имени (справа налево)."""
        actions = self._actions_for(index)
        if not actions:
            return []
        fm = QFontMetrics(_btn_font())
        name_h = QFontMetrics(_name_font()).height()
        btn_h = fm.height() + _BTN_PAD_Y * 2 + _BTN_SHADOW
        top = option.rect.top() + _PAD_Y + (name_h - btn_h) // 2
        right = option.rect.right() - _PAD_R
        rects: list[tuple[QRect, str]] = []
        for label in reversed(actions):
            w = fm.horizontalAdvance(label) + _BTN_PAD_X * 2 + _BTN_SHADOW
            rects.append((QRect(right - w, top, w, btn_h), label))
            right -= w + 8
        return rects

    def _quote_of(self, index) -> tuple[str, int]:
        """Строка цитаты «↩ автор — текст» и её высота (0 — без цитаты)."""
        author = index.data(_REPLY_AUTHOR_ROLE)
        if not author:
            return "", 0
        snippet = index.data(_REPLY_SNIPPET_ROLE) or ""
        text = f"↩ {author} — {snippet}" if snippet else f"↩ {author}"
        return text, QFontMetrics(_small_mono_font()).height() + 6

    def _scaled_image(self, cw: int, pixmap: QPixmap) -> QPixmap:
        scaled = pixmap.scaledToWidth(cw, Qt.SmoothTransformation) if pixmap.width() > cw else pixmap
        if scaled.height() > _MAX_IMAGE_H:
            scaled = scaled.scaledToHeight(_MAX_IMAGE_H, Qt.SmoothTransformation)
        return scaled

    def _layout_segments(self, cw: int, body: str) -> tuple[list[tuple[bool, str, int]], int]:
        """Вернуть [(is_code, text, h)] и суммарную высоту; у кода h включает шапку."""
        flags = int(Qt.TextWordWrap)
        bf = QFontMetrics(_body_font())
        cf = QFontMetrics(_mono_font())
        laid: list[tuple[bool, str, int]] = []
        total = 0
        for is_code, text in _split_segments(body):
            fm = cf if is_code else bf
            inner_w = cw - (_CODE_PAD * 2 if is_code else 0)
            h = fm.boundingRect(QRect(0, 0, max(1, inner_w), 100000), flags, text).height()
            if is_code:
                h += _CODE_HEAD + _CODE_PAD * 2
            laid.append((is_code, text, h))
            total += h
        if len(laid) > 1:
            total += _SEG_GAP * (len(laid) - 1)
        return laid, total

    def _content_geom(self, option, index):
        """Вернуть (cx, cw, name_h, kind, payload, content_h).

        ``kind``/``payload``: ``("image", QPixmap)`` готовое превью для отрисовки,
        ``("segments", laid)`` список сегментов текст/код из ``_layout_segments``.
        """
        cx = _PAD_L
        cw = max(60, option.rect.width() - cx - _PAD_R)
        name_h = QFontMetrics(_name_font()).height()

        pixmap = index.data(_IMAGE_ROLE)
        if index.data(_KIND_ROLE) == "image" and isinstance(pixmap, QPixmap) and not pixmap.isNull():
            scaled = self._scaled_image(cw - 2, pixmap)  # -2 на рамку
            return cx, cw, name_h, "image", scaled, scaled.height() + 2
        body = index.data(Qt.DisplayRole) or ""
        laid, total_h = self._layout_segments(cw, body)
        return cx, cw, name_h, "segments", laid, total_h

    def sizeHint(self, option, index):
        _, _, name_h, _, _, content_h = self._content_geom(option, index)
        _, quote_h = self._quote_of(index)
        return QSize(
            option.rect.width(),
            _PAD_Y + name_h + quote_h + _NAME_GAP + content_h + _PAD_Y,
        )

    def _copy_button_rects(self, option, index) -> list[tuple[QRect, str]]:
        """Кликабельные зоны «КОПИРОВАТЬ» в шапках код-блоков (для editorEvent)."""
        cx, cw, name_h, kind, payload, _h = self._content_geom(option, index)
        if kind != "segments":
            return []
        _, quote_h = self._quote_of(index)
        rects: list[tuple[QRect, str]] = []
        fm = QFontMetrics(_btn_font())
        x = option.rect.left() + cx
        y = option.rect.top() + _PAD_Y + name_h + quote_h + _NAME_GAP
        btn_h = fm.height() + _BTN_PAD_Y * 2 + _BTN_SHADOW
        for is_code, text, h in payload:
            if is_code:
                w = fm.horizontalAdvance("КОПИРОВАТЬ") + _BTN_PAD_X * 2 + _BTN_SHADOW
                rects.append((QRect(
                    x + cw - w - 6, y + (_CODE_HEAD - btn_h) // 2, w, btn_h
                ), text))
            y += h + _SEG_GAP
        return rects

    def _button_at(self, option, index, pos):
        """(rect, kind, payload) кнопки под курсором: действие или копирование."""
        for rect, label in self._action_rects(option, index):
            if rect.contains(pos):
                return rect, "action", label
        for rect, code in self._copy_button_rects(option, index):
            if rect.contains(pos):
                return rect, "copy", code
        return None

    def editorEvent(self, event, model, option, index):
        etype = event.type()
        if (
            etype in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease)
            and event.button() == Qt.LeftButton
        ):
            hit = self._button_at(option, index, event.position().toPoint())
            if etype == QEvent.MouseButtonPress:
                if hit is not None:
                    # анимация нажатия: paint утапливает кнопку в тень
                    self._view._pressed_rect = QRect(hit[0])
                    self._view.viewport().update()
                    return True
            else:
                was_pressed = getattr(self._view, "_pressed_rect", None)
                if was_pressed is not None:
                    self._view._pressed_rect = None
                    self._view.viewport().update()
                if hit is not None:
                    rect, kind, payload = hit
                    if kind == "copy":
                        QGuiApplication.clipboard().setText(payload)
                    else:
                        local_id = index.data(_MESSAGE_ID_ROLE)
                        if local_id is not None:
                            if payload == "ОТВЕТИТЬ":
                                self._view.reply_requested.emit(local_id)
                            elif payload == "ИЗМЕНИТЬ":
                                self._view.edit_requested.emit(local_id)
                            elif payload == "УДАЛИТЬ":
                                self._view.delete_requested.emit(local_id)
                    return True
        return super().editorEvent(event, model, option, index)

    def paint(self, painter, option, index):
        t = theme.tokens()
        own = index.data(_DIRECTION_ROLE) == "out"
        author = index.data(_AUTHOR_ROLE) or ("я" if own else "Собеседник")
        when = index.data(_TIME_ROLE) or ""
        cx, cw, name_h, kind, payload, _content_h = self._content_geom(option, index)
        r = option.rect

        painter.save()
        painter.setRenderHint(painter.RenderHint.Antialiasing, False)

        # hairline-разделитель сверху (кроме первой строки) — как в вебе
        if index.row() > 0:
            painter.setPen(QPen(QColor(t["border2"]), 1))
            painter.drawLine(r.left() + _PAD_L, r.top(), r.right() - _PAD_R, r.top())

        top = r.top() + _PAD_Y
        x = r.left() + cx

        # имя (своё — кобальтом, как в вебе) + mono-время
        nf = _name_font()
        painter.setFont(nf)
        painter.setPen(QColor(t["accent"] if own else t["text"]))
        nm = QFontMetrics(nf)
        painter.drawText(QRect(x, top, cw, name_h), Qt.AlignVCenter | Qt.AlignLeft, author)
        meta_x = x + nm.horizontalAdvance(author) + 12
        sfm0 = QFontMetrics(_small_mono_font())
        if when:
            painter.setFont(_small_mono_font())
            painter.setPen(QColor(t["text3"]))
            painter.drawText(
                QRect(meta_x, top, cw, name_h), Qt.AlignVCenter | Qt.AlignLeft, when
            )
            meta_x += sfm0.horizontalAdvance(when) + 12
        # красная пометка оптимистичной отправки: ещё не подтверждено сервером
        status = index.data(_STATUS_ROLE)
        if own and status in ("pending", "failed"):
            mark = "● НЕ ДОСТАВЛЕНО" if status == "pending" else "● НЕ ОТПРАВЛЕНО"
            painter.setFont(_small_mono_font())
            painter.setPen(QColor(t["warn"]))
            painter.drawText(
                QRect(meta_x, top, cw, name_h), Qt.AlignVCenter | Qt.AlignLeft, mark
            )

        # действия строки (ОТВЕТИТЬ / ИЗМЕНИТЬ / УДАЛИТЬ) — объёмные кнопки справа,
        # видимы только у наведённой строки (гейт в _actions_for)
        pressed_rect = getattr(self._view, "_pressed_rect", None)
        for rect, label in self._action_rects(option, index):
            _paint_button(
                painter, rect, label, t,
                accent=(label == "ОТВЕТИТЬ"), pressed=(rect == pressed_rect),
            )

        # цитата ответа («↩ автор — текст») — между именем и телом, как в вебе
        quote, quote_h = self._quote_of(index)
        if quote_h:
            painter.setFont(_small_mono_font())
            painter.setPen(QColor(t["text3"]))
            qfm = QFontMetrics(_small_mono_font())
            painter.drawText(
                QRect(x, top + name_h, cw, quote_h), Qt.AlignVCenter | Qt.AlignLeft,
                qfm.elidedText(quote, Qt.ElideRight, cw),
            )

        content_top = top + name_h + quote_h + _NAME_GAP
        if kind == "image":
            # тонкая рамка вокруг превью — паритет с вебом
            frame = QRect(x, content_top, payload.width() + 2, payload.height() + 2)
            painter.fillRect(frame, QColor(t["surface"]))
            painter.setPen(QPen(QColor(t["border2"]), 1))
            painter.drawRect(frame.adjusted(0, 0, -1, -1))
            painter.drawPixmap(x + 1, content_top + 1, payload)
        else:
            flags = int(Qt.TextWordWrap)
            y = content_top
            small = _small_mono_font()
            sfm = QFontMetrics(small)
            for is_code, text, h in payload:
                if is_code:
                    # шапка «//// CODE … КОПИРОВАТЬ» + блок кода — как в вебе
                    block = QRect(x, y, cw, h)
                    painter.fillRect(block, QColor(t["surface3"]))
                    painter.setPen(QPen(QColor(t["border2"]), 1))
                    painter.drawRect(block.adjusted(0, 0, -1, -1))
                    painter.drawLine(x, y + _CODE_HEAD, x + cw - 1, y + _CODE_HEAD)

                    painter.setFont(small)
                    painter.setPen(QColor(t["text2"]))
                    head = QRect(x + _CODE_PAD, y, cw - _CODE_PAD * 2, _CODE_HEAD)
                    painter.drawText(head, Qt.AlignVCenter | Qt.AlignLeft, "//// CODE")
                    bfm = QFontMetrics(_btn_font())
                    bw = bfm.horizontalAdvance("КОПИРОВАТЬ") + _BTN_PAD_X * 2 + _BTN_SHADOW
                    bh = bfm.height() + _BTN_PAD_Y * 2 + _BTN_SHADOW
                    copy_rect = QRect(x + cw - bw - 6, y + (_CODE_HEAD - bh) // 2, bw, bh)
                    _paint_button(
                        painter, copy_rect, "КОПИРОВАТЬ", t,
                        pressed=(copy_rect == pressed_rect),
                    )

                    painter.setFont(_mono_font())
                    painter.setPen(QColor(t["text"]))
                    painter.drawText(
                        QRect(x + _CODE_PAD, y + _CODE_HEAD + _CODE_PAD,
                              cw - _CODE_PAD * 2, h - _CODE_HEAD - _CODE_PAD * 2),
                        flags, text,
                    )
                else:
                    painter.setFont(_body_font())
                    painter.setPen(QColor(t["text"]))
                    painter.drawText(QRect(x, y, cw, h), flags, text)
                y += h + _SEG_GAP
        painter.restore()


def _fmt_when(epoch) -> str:
    """Веб-формат времени (``format_ts`` из vsc_web): «сегодня 15:27» /
    «вчера 15:27» / «13 май 15:27» — в локальной таймзоне."""
    if not epoch:
        return ""
    try:
        d = _dt.datetime.fromtimestamp(float(epoch))
    except (TypeError, ValueError, OSError, OverflowError):
        return ""
    time_str = d.strftime("%H:%M")
    today = _dt.date.today()
    if d.date() == today:
        return f"сегодня {time_str}"
    if (today - d.date()).days == 1:
        return f"вчера {time_str}"
    return f"{d.day} {_MONTHS[d.month - 1]} {time_str}"


def _fmt_size(n: int) -> str:
    if n >= 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} МБ"
    if n >= 1024:
        return f"{n / 1024:.0f} КБ"
    return f"{n} Б"


def _display_text(m: dict) -> str:
    kind = m.get("kind")
    filename = m.get("filename") or "файл"
    if kind == "image":
        if m["body"] is None:
            return f"🖼 {filename} — загрузка…"
        return f"🖼 {filename} ({_fmt_size(len(m['body']))})"
    if kind == "file":
        if m["body"] is None:
            return f"📎 {filename} — нажмите, чтобы загрузить"
        return f"📎 {filename} ({_fmt_size(len(m['body']))})"
    return m["body"].decode("utf-8", "replace") if m["body"] is not None else ""


class ChatView(QListWidget):
    media_fetch_requested = Signal(int)  # message id — тело ещё не докачано
    reply_requested = Signal(int)        # local message id — «Ответить»
    edit_requested = Signal(int)         # local message id — «Изменить» (своё)
    delete_requested = Signal(int)       # local message id — «Удалить» (своё)

    def __init__(self, parent=None):
        super().__init__(parent)
        # Действия строк доступны только в «Центре» с активной сессией —
        # выставляет MainWindow при смене режима/сессии.
        self.actions_enabled = False
        self._hover_row = -1        # кнопки действий видны только у этой строки
        self._pressed_rect = None   # кнопка, «утопленная» нажатием (анимация)
        self.setMouseTracking(True)
        self.setObjectName("ChatView")
        self.setItemDelegate(_JournalDelegate(self))
        self.setSelectionMode(QListWidget.NoSelection)
        self.setFocusPolicy(Qt.NoFocus)
        self.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.setUniformItemSizes(False)
        self.setSpacing(0)
        self.setWordWrap(True)
        self.itemDoubleClicked.connect(self._on_double_click)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)

    def show_messages(
        self, messages: list[dict], *,
        peer_label: str = "Собеседник", own_label: str = "я",
        own_sender: str | None = None,
    ) -> None:
        """``own_sender`` — логин аккаунта «Центра»: входящие с этим отправителем
        (собственные сообщения, отправленные из веба) рисуются как свои —
        с кобальтовым именем и кнопками ИЗМЕНИТЬ/УДАЛИТЬ."""
        self.clear()
        for m in messages:
            own = m["direction"] == "out" or (
                own_sender is not None and m.get("sender") == own_sender
            )
            author = own_label if own else (m.get("sender") or peer_label)
            item = QListWidgetItem(_display_text(m))
            item.setData(_DIRECTION_ROLE, "out" if own else m["direction"])
            item.setData(_AUTHOR_ROLE, author)
            item.setData(_TIME_ROLE, _fmt_when(m.get("sent_at") or m.get("received_at")))
            item.setData(_KIND_ROLE, m.get("kind", "text"))
            item.setData(_MESSAGE_ID_ROLE, m.get("id"))
            item.setData(_WIRE_ROLE, m.get("wire_seq"))
            item.setData(_REPLY_AUTHOR_ROLE, m.get("reply_author"))
            item.setData(_REPLY_SNIPPET_ROLE, m.get("reply_snippet"))
            item.setData(_STATUS_ROLE, m.get("status"))
            if m.get("kind") == "image" and m["body"] is not None:
                pix = QPixmap()
                pix.loadFromData(m["body"])
                item.setData(_IMAGE_ROLE, pix)
            if m.get("kind") == "file":
                item.setData(_FILE_BODY_ROLE, m["body"])
                item.setData(_FILENAME_ROLE, m.get("filename"))
            self.addItem(item)
        self.scrollToBottom()

    def mouseMoveEvent(self, event) -> None:
        row = self.indexAt(event.position().toPoint()).row()
        if row != self._hover_row:
            self._hover_row = row
            self.viewport().update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        if self._hover_row != -1:
            self._hover_row = -1
            self._pressed_rect = None
            self.viewport().update()
        super().leaveEvent(event)

    def _on_double_click(self, item: QListWidgetItem) -> None:
        if item.data(_KIND_ROLE) != "file":
            return
        body = item.data(_FILE_BODY_ROLE)
        if body is None:
            # Тело ещё не докачано (ленивая докачка «Центра») — первый клик
            # запускает докачку; второй (после перерисовки) сохранит файл.
            message_id = item.data(_MESSAGE_ID_ROLE)
            if message_id is not None:
                self.media_fetch_requested.emit(message_id)
            return
        filename = item.data(_FILENAME_ROLE) or "файл"
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить файл", filename)
        if not path:
            return
        with open(path, "wb") as fh:
            fh.write(body)

    def _on_context_menu(self, pos) -> None:
        item = self.itemAt(pos)
        if item is None:
            return
        segments = _split_segments(item.text())
        code_parts = [text for is_code, text in segments if is_code]
        if not code_parts:
            return
        menu = QMenu(self)
        action = menu.addAction("Копировать код")
        chosen = menu.exec(self.mapToGlobal(pos))
        if chosen == action:
            QGuiApplication.clipboard().setText("\n\n".join(code_parts))
