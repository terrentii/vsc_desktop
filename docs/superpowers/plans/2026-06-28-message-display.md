# Отображение сообщений (под-проект A) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Завести в модели сообщения автора, серверное время и колонку медиа, провести их через синк, и переписать ленту чата как в `vsc_web` — цветное имя отправителя, корректное время, блоки кода с копированием, рендер медиа.

**Architecture:** Хранилище получает 3 новые колонки (миграция v3) и расширенный `MessagesRepo.add`. `SyncEngine._ingest` (единственная точка персиста входящих) прокидывает `sender` и распарсенное серверное время. UI остаётся `QListWidget`, но каждая строка рисуется виджетом `MessageRow` через `setItemWidget` — это даёт интерактивные `CodeBlock` (кнопка «Копировать») и `MediaView`. Парсер `split_segments` режет тело по ```` ``` ````.

**Tech Stack:** Python 3.13, SQLCipher (sqlcipher3), PySide6, pytest (+ pytest-asyncio, asyncio_mode=auto).

**Спека:** `docs/superpowers/specs/2026-06-28-message-display-design.md`.

---

## Подготовка окружения (один раз в сессии исполнения)

libsodium в Nix не на пути линковщика; путь дрейфует. Выставить перед прогоном тестов:

```bash
export LD_LIBRARY_PATH=$(dirname $(find /nix/store -name libsodium.so 2>/dev/null | head -1))
export PYTHONPATH=src
export QT_QPA_PLATFORM=offscreen
```

Прогон одного теста: `.venv/bin/python -m pytest <путь>::<тест> -v`
Прогон всего: `.venv/bin/python -m pytest -q`

---

## Файловая структура

- Modify: `src/mys_storage/schema.py` — миграция v3 (колонки `author`, `created_ts`, `media`).
- Modify: `src/mys_storage/repositories.py` — `MessagesRepo.add` принимает `author/created_ts/media`.
- Modify: `src/mys_centralized/sync.py` — хелпер `_parse_iso` + проводка в `_ingest`.
- Create: `src/mys_ui/widgets/message_text.py` — парсер `split_segments`.
- Create: `src/mys_ui/widgets/code_block.py` — виджет `CodeBlock`.
- Create: `src/mys_ui/widgets/media_view.py` — виджет `MediaView`.
- Modify: `src/mys_ui/widgets/chat_view.py` — `MessageRow` + `show_messages` через `setItemWidget`.
- Test: `tests/test_repositories.py`, `tests/test_centralized_sync.py`, `tests/test_message_text.py`, `tests/test_code_block.py`, `tests/test_media_view.py`, `tests/test_chat_view.py`.

---

## Task 1: Миграция схемы + расширение `MessagesRepo.add`

**Files:**
- Modify: `src/mys_storage/schema.py:52-58` (список `MIGRATIONS`)
- Modify: `src/mys_storage/repositories.py:114-125` (`MessagesRepo.add`)
- Test: `tests/test_repositories.py`

- [ ] **Step 1: Написать падающий тест**

Добавить в конец `tests/test_repositories.py`:

```python
def test_messages_store_author_created_ts_media(tmp_path):
    v = _vault(tmp_path)
    conv = v.conversations.add(mode="centralized", room_id=b"1", title="g")
    mid = v.messages.add(
        conv, direction="in", body=b"yo", status="received",
        author="alice", created_ts=1719500000.0, media="x.png",
    )
    row = [m for m in v.messages.list(conv) if m["id"] == mid][0]
    assert row["author"] == "alice"
    assert row["created_ts"] == 1719500000.0
    assert row["media"] == "x.png"
    # Старый вызов без новых параметров — значения NULL.
    mid2 = v.messages.add(conv, direction="out", body=b"hi", status="sent")
    row2 = [m for m in v.messages.list(conv) if m["id"] == mid2][0]
    assert row2["author"] is None and row2["created_ts"] is None and row2["media"] is None
    v.close()
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `.venv/bin/python -m pytest tests/test_repositories.py::test_messages_store_author_created_ts_media -v`
Expected: FAIL — `OperationalError: table messages has no column named author` (или `KeyError: 'author'`).

- [ ] **Step 3: Добавить миграцию v3**

В `src/mys_storage/schema.py` после блока `(2, [...])` (перед закрывающей `]` списка `MIGRATIONS`) добавить:

```python
    # v3 — отображение сообщений (под-проект A): автор, серверное время, медиа.
    (3, [
        "ALTER TABLE messages ADD COLUMN author TEXT",
        "ALTER TABLE messages ADD COLUMN created_ts REAL",
        "ALTER TABLE messages ADD COLUMN media TEXT",
    ]),
```

- [ ] **Step 4: Расширить `MessagesRepo.add`**

Заменить метод `add` в `src/mys_storage/repositories.py` целиком на:

```python
    def add(self, conversation_id, *, direction, body, status, wire_seq=None,
            client_msg_id=None, author=None, created_ts=None, media=None) -> int:
        now = time.time()
        cur = self._c.execute(
            "INSERT INTO messages(conversation_id, direction, body, status, wire_seq,"
            " client_msg_id, sent_at, received_at, author, created_ts, media)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (conversation_id, direction, body, status, wire_seq, client_msg_id,
             now if direction == "out" else None,
             now if direction == "in" else None,
             author, created_ts, media),
        )
        self._c.commit()
        return cur.lastrowid
```

- [ ] **Step 5: Запустить тест — убедиться, что проходит**

Run: `.venv/bin/python -m pytest tests/test_repositories.py -v`
Expected: PASS (включая существующие тесты репозиториев).

- [ ] **Step 6: Commit**

```bash
git add src/mys_storage/schema.py src/mys_storage/repositories.py tests/test_repositories.py
git commit -m "feat(storage): колонки author/created_ts/media в messages (миграция v3)"
```

---

## Task 2: Парсинг серверного времени + проводка автора в синк

**Files:**
- Modify: `src/mys_centralized/sync.py` (импорт `datetime`, хелпер `_parse_iso`, вызов `add` в `_ingest`)
- Test: `tests/test_centralized_sync.py`

- [ ] **Step 1: Написать падающий тест**

Добавить в конец `tests/test_centralized_sync.py`:

```python
def test_ingest_stores_author_and_created_ts(vault):
    eng = SyncEngine(vault, rest=None)
    conv = vault.conversations.add(mode="centralized", room_id=b"5", title="g")
    eng._ingest(conv, RemoteMessage(
        id=1, room_id=5, sender="alice", body="hi",
        created_at="2024-06-27T12:00:00Z",
    ))
    row = vault.messages.list(conv)[0]
    assert row["author"] == "alice"
    assert row["created_ts"] == pytest.approx(1719489600.0)


def test_ingest_bad_created_at_yields_none(vault):
    eng = SyncEngine(vault, rest=None)
    conv = vault.conversations.add(mode="centralized", room_id=b"6", title="g")
    eng._ingest(conv, RemoteMessage(
        id=2, room_id=6, sender="bob", body="yo", created_at="t",
    ))
    row = vault.messages.list(conv)[0]
    assert row["author"] == "bob"
    assert row["created_ts"] is None
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `.venv/bin/python -m pytest tests/test_centralized_sync.py::test_ingest_stores_author_and_created_ts -v`
Expected: FAIL — `assert None == 'alice'` (author не сохраняется).

- [ ] **Step 3: Добавить `_parse_iso` в sync.py**

В `src/mys_centralized/sync.py` заменить блок импортов (строки с `import uuid` и ниже до `from .models`) на:

```python
import uuid
from datetime import datetime, timezone

from .models import RemoteMessage
```

И сразу после `MODE = "centralized"` добавить:

```python
def _parse_iso(value) -> float | None:
    """ISO-таймстамп сервера → epoch (сек, UTC). Пустой/битый → None."""
    if not value:
        return None
    try:
        s = str(value)
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (ValueError, TypeError):
        return None
```

- [ ] **Step 4: Прокинуть author + created_ts в `_ingest`**

В `src/mys_centralized/sync.py`, в методе `_ingest`, заменить финальный вызов `add` (тот, что с `direction="in"`) на:

```python
        local_id = self._vault.messages.add(
            conv_id, direction="in", body=msg.body.encode("utf-8"),
            status="received", wire_seq=msg.id,
            author=msg.sender, created_ts=_parse_iso(msg.created_at),
        )
```

- [ ] **Step 5: Запустить тесты — убедиться, что проходят**

Run: `.venv/bin/python -m pytest tests/test_centralized_sync.py -v`
Expected: PASS (новые два + существующие тесты синка).

- [ ] **Step 6: Commit**

```bash
git add src/mys_centralized/sync.py tests/test_centralized_sync.py
git commit -m "feat(central): синк сохраняет sender и серверное время сообщения"
```

---

## Task 3: Парсер сегментов `split_segments`

**Files:**
- Create: `src/mys_ui/widgets/message_text.py`
- Test: `tests/test_message_text.py`

- [ ] **Step 1: Написать падающий тест**

Создать `tests/test_message_text.py`:

```python
from mys_ui.widgets.message_text import split_segments


def test_plain_text_single_segment():
    assert split_segments("привет мир") == [("text", "привет мир")]


def test_mixed_text_and_code():
    body = "до\n```\nx = 1\n```\nпосле"
    assert split_segments(body) == [
        ("text", "до\n"),
        ("code", "x = 1"),
        ("text", "\nпосле"),
    ]


def test_unterminated_fence_stays_text():
    assert split_segments("a```b") == [("text", "a```b")]


def test_empty_input():
    assert split_segments("") == [("text", "")]


def test_only_code():
    assert split_segments("```\ncode\n```") == [("code", "code")]
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `.venv/bin/python -m pytest tests/test_message_text.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mys_ui.widgets.message_text'`.

- [ ] **Step 3: Реализовать парсер**

Создать `src/mys_ui/widgets/message_text.py`:

```python
"""Разбор тела сообщения на сегменты текст/код по ```-ограждениям.

Повторяет семантику серверного `render_text` (vsc_web, app.py): чётные части —
текст, нечётные — код с обрезкой ведущего/хвостового перевода строки.
"""

import re

_FENCE = re.compile(r"```([\s\S]*?)```")


def split_segments(body: str) -> list[tuple[str, str]]:
    parts = _FENCE.split(body or "")
    out: list[tuple[str, str]] = []
    for i, part in enumerate(parts):
        if i % 2 == 0:
            if part:
                out.append(("text", part))
        else:
            code = re.sub(r"^\r?\n", "", re.sub(r"\r?\n$", "", part))
            out.append(("code", code))
    return out or [("text", "")]
```

- [ ] **Step 4: Запустить тест — убедиться, что проходит**

Run: `.venv/bin/python -m pytest tests/test_message_text.py -v`
Expected: PASS (5 тестов).

- [ ] **Step 5: Commit**

```bash
git add src/mys_ui/widgets/message_text.py tests/test_message_text.py
git commit -m "feat(ui): парсер сегментов сообщения (текст/код)"
```

---

## Task 4: Виджет `CodeBlock`

**Files:**
- Create: `src/mys_ui/widgets/code_block.py`
- Test: `tests/test_code_block.py`

- [ ] **Step 1: Написать падающий тест**

Создать `tests/test_code_block.py`:

```python
from PySide6.QtWidgets import QApplication

from mys_ui.widgets.code_block import CodeBlock


def test_code_block_shows_code_and_copies(qtbot):
    cb = CodeBlock("x = 1\ny = 2")
    qtbot.addWidget(cb)
    assert cb.pre.toPlainText() == "x = 1\ny = 2"
    cb._copy()
    assert QApplication.clipboard().text() == "x = 1\ny = 2"
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `.venv/bin/python -m pytest tests/test_code_block.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mys_ui.widgets.code_block'`.

- [ ] **Step 3: Реализовать виджет**

Создать `src/mys_ui/widgets/code_block.py`:

```python
"""Блок кода: бар «//// code» + кнопка «Копировать» + моноширинный pre.

Структура повторяет .code-block из vsc_web (без подсветки синтаксиса).
"""

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from mys_ui import theme


class CodeBlock(QWidget):
    def __init__(self, code: str, parent=None):
        super().__init__(parent)
        self._code = code
        t = theme.tokens()
        self.setObjectName("CodeBlock")
        self.setStyleSheet(
            f"#CodeBlock {{ border: 1px solid {t['border2']}; }}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        bar = QWidget()
        bar.setObjectName("CodeBar")
        bar.setStyleSheet(f"#CodeBar {{ background: {t['surface']}; }}")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(10, 5, 10, 5)
        label = QLabel("//// code")
        label.setStyleSheet(
            f"color: {t['text3']}; font-family: monospace;"
            " font-size: 10px; letter-spacing: 2px;"
        )
        self.copy_btn = QPushButton("Копировать")
        self.copy_btn.setCursor(self.copy_btn.cursor())
        self.copy_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {t['text3']};"
            f" border: 1px solid {t['border2']}; padding: 2px 10px;"
            " font-family: monospace; font-size: 10px; }"
        )
        self.copy_btn.clicked.connect(self._copy)
        bl.addWidget(label)
        bl.addStretch()
        bl.addWidget(self.copy_btn)
        root.addWidget(bar)

        self.pre = QPlainTextEdit()
        self.pre.setReadOnly(True)
        self.pre.setPlainText(code)
        self.pre.setFrameShape(QPlainTextEdit.NoFrame)
        mono = QFont("monospace")
        mono.setStyleHint(QFont.Monospace)
        mono.setPixelSize(12)
        self.pre.setFont(mono)
        self.pre.setStyleSheet(
            f"QPlainTextEdit {{ background: {t['surface']}; color: {t['text']};"
            " padding: 8px 12px; }"
        )
        # высота под контент (без внутреннего скролла на коротком коде)
        lines = code.count("\n") + 1
        self.pre.setFixedHeight(min(max(lines, 1), 20) * 18 + 18)
        root.addWidget(self.pre)

    def _copy(self) -> None:
        QApplication.clipboard().setText(self._code)
```

Примечание: токен `surface` существует в `theme.tokens()` (dark `#0d1936`, light `#ffffff`) — фон кода. Прочие ключи темы: `bg`, `text`, `text3`, `border2`, `line`, `accent`.

- [ ] **Step 4: Запустить тест — убедиться, что проходит**

Run: `.venv/bin/python -m pytest tests/test_code_block.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mys_ui/widgets/code_block.py tests/test_code_block.py
git commit -m "feat(ui): виджет CodeBlock с копированием"
```

---

## Task 5: Виджет `MediaView`

**Files:**
- Create: `src/mys_ui/widgets/media_view.py`
- Test: `tests/test_media_view.py`

- [ ] **Step 1: Написать падающий тест**

Создать `tests/test_media_view.py`:

```python
from PySide6.QtGui import QColor, QPixmap

from mys_ui.widgets.media_view import MediaView


def test_image_ref_renders_pixmap(qtbot, tmp_path):
    p = tmp_path / "pic.png"
    pm = QPixmap(20, 20)
    pm.fill(QColor("red"))
    assert pm.save(str(p), "PNG")
    mv = MediaView(str(p))
    qtbot.addWidget(mv)
    assert mv.is_image is True
    assert not mv.image.pixmap().isNull()


def test_non_image_ref_renders_link(qtbot, tmp_path):
    mv = MediaView("doc_report.pdf")
    qtbot.addWidget(mv)
    assert mv.is_image is False
    assert "doc_report.pdf" in mv.link.text()
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `.venv/bin/python -m pytest tests/test_media_view.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mys_ui.widgets.media_view'`.

- [ ] **Step 3: Реализовать виджет**

Создать `src/mys_ui/widgets/media_view.py`:

```python
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
```

- [ ] **Step 4: Запустить тест — убедиться, что проходит**

Run: `.venv/bin/python -m pytest tests/test_media_view.py -v`
Expected: PASS (2 теста).

- [ ] **Step 5: Commit**

```bash
git add src/mys_ui/widgets/media_view.py tests/test_media_view.py
git commit -m "feat(ui): виджет MediaView (картинка/файл)"
```

---

## Task 6: `MessageRow` + перевод `ChatView` на `setItemWidget`

**Files:**
- Modify: `src/mys_ui/widgets/chat_view.py` (целиком переписать)
- Test: `tests/test_chat_view.py`

- [ ] **Step 1: Написать падающий тест**

Создать `tests/test_chat_view.py`:

```python
from mys_ui import theme
from mys_ui.widgets.chat_view import ChatView, MessageRow
from mys_ui.widgets.code_block import CodeBlock
from mys_ui.widgets.media_view import MediaView


def _msg(direction, body, **extra):
    base = {
        "direction": direction, "body": body.encode("utf-8"),
        "author": None, "created_ts": None, "sent_at": None, "received_at": None,
        "media": None,
    }
    base.update(extra)
    return base


def test_own_message_uses_accent_name(qtbot):
    cv = ChatView()
    qtbot.addWidget(cv)
    cv.show_messages([_msg("out", "привет")], peer_label="bob")
    row = cv.itemWidget(cv.item(0))
    assert isinstance(row, MessageRow)
    assert row.author == "я"
    assert row.author_color == theme.tokens()["accent"]


def test_incoming_message_uses_author_name(qtbot):
    cv = ChatView()
    qtbot.addWidget(cv)
    cv.show_messages([_msg("in", "йо", author="alice")], peer_label="bob")
    row = cv.itemWidget(cv.item(0))
    assert row.author == "alice"
    assert row.author_color == theme.tokens()["text"]


def test_incoming_without_author_falls_back_to_peer(qtbot):
    cv = ChatView()
    qtbot.addWidget(cv)
    cv.show_messages([_msg("in", "йо")], peer_label="bob")
    assert cv.itemWidget(cv.item(0)).author == "bob"


def test_code_segment_renders_code_block(qtbot):
    cv = ChatView()
    qtbot.addWidget(cv)
    cv.show_messages([_msg("in", "до\n```\ncode\n```", author="a")], peer_label="b")
    row = cv.itemWidget(cv.item(0))
    assert len(row.findChildren(CodeBlock)) == 1


def test_media_renders_media_view(qtbot, tmp_path):
    cv = ChatView()
    qtbot.addWidget(cv)
    cv.show_messages([_msg("in", "файл", author="a", media="doc.pdf")], peer_label="b")
    row = cv.itemWidget(cv.item(0))
    assert len(row.findChildren(MediaView)) == 1


def test_time_prefers_created_ts(qtbot):
    cv = ChatView()
    qtbot.addWidget(cv)
    cv.show_messages(
        [_msg("in", "йо", author="a", created_ts=1719489600.0, received_at=1.0)],
        peer_label="b",
    )
    row = cv.itemWidget(cv.item(0))
    assert row.when != ""
    # время форматируется из created_ts, не из received_at (1970)
    assert not row.when.startswith("00:00")


def test_item_text_holds_raw_body(qtbot):
    cv = ChatView()
    qtbot.addWidget(cv)
    cv.show_messages([_msg("in", "привет", author="a")], peer_label="b")
    assert cv.count() == 1
    assert "привет" in cv.item(0).text()
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `.venv/bin/python -m pytest tests/test_chat_view.py -v`
Expected: FAIL — `ImportError: cannot import name 'MessageRow' from 'mys_ui.widgets.chat_view'`.

- [ ] **Step 3: Переписать `chat_view.py`**

Заменить `src/mys_ui/widgets/chat_view.py` целиком на:

```python
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
```

- [ ] **Step 4: Запустить тест — убедиться, что проходит**

Run: `.venv/bin/python -m pytest tests/test_chat_view.py -v`
Expected: PASS (7 тестов).

- [ ] **Step 5: Проверить существующие UI-тесты не сломались**

Run: `.venv/bin/python -m pytest tests/test_ui_main_window.py tests/test_ui_centralized.py -v`
Expected: PASS (они опираются на `chat.count()` и `chat.item(i).text()` — оба сохранены).

- [ ] **Step 6: Commit**

```bash
git add src/mys_ui/widgets/chat_view.py tests/test_chat_view.py
git commit -m "feat(ui): MessageRow с цветным автором, кодом и медиа в ленте чата"
```

---

## Task 7: Полный прогон и проверка приложения

**Files:** —

- [ ] **Step 1: Прогнать весь набор тестов**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS — все тесты (≥192 + новые).

- [ ] **Step 2: Запустить приложение и убедиться, что стартует без ошибок**

```bash
.venv/bin/python -m mys_ui > /tmp/mys_run.log 2>&1 &
sleep 5
pgrep -fc mys_ui    # ожидается ≥1
cat /tmp/mys_run.log # ожидается пусто (без трейсбеков)
pkill -f 'python -m mys_ui'
```

- [ ] **Step 3: Финальный коммит (если остались несохранённые мелочи)**

```bash
git add -A
git commit -m "chore: завершение под-проекта A (отображение сообщений)" || echo "нечего коммитить"
```

---

## Self-Review (выполнено при написании плана)

- **Покрытие спеки:** A1 → Task 1–2; A2/A3 → Task 6; A4 → Task 3–4; A5 → Task 5; A6 — границы соблюдены (storage/sync/ui раздельно); A7 → тесты в каждой задаче + Task 7.
- **Плейсхолдеров нет:** весь код приведён полностью.
- **Согласованность типов:** `MessagesRepo.add(... author, created_ts, media)` — те же имена в Task 1, sync (Task 2), и ключи dict в UI (Task 6: `m.get("author")`, `m.get("created_ts")`, `m.get("media")`). `MessageRow` атрибуты `author/author_color/when` — те же в тесте и реализации. `CodeBlock.pre`, `CodeBlock._copy`, `MediaView.is_image/image/link` — согласованы тест↔код.
- **Токены темы:** Task 4/5/6 используют существующие ключи `surface`/`bg`/`text`/`text3`/`border2`/`line`/`accent` (сверено по `theme.py`).
```
