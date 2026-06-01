# P2P GUI Wiring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Подключить уже реализованный `mys_decentralized.P2PService` к GUI, чтобы по секретной фразе + адресу rendezvous поднимался реальный защищённый канал между двумя машинами.

**Architecture:** Зеркалим паттерн централизованного режима: фабрика сервиса в `app.py`, ленивый жизненный цикл в `AppController`, мост Qt-сигналов в `MainWindow` для маршалинга колбэков сервиса в UI-поток. Старт сессии блокирующий (коннект до 10с) → выносится в worker-поток. Адрес rendezvous вводится в `PhraseDialog`. LAN-проверка через скрипт-runner встроенного `RendezvousServer`.

**Tech Stack:** Python 3.13, PySide6 (Qt), `mys_decentralized` (asyncio P2P), pytest + pytest-qt + pytest-asyncio.

---

## Контекст и инварианты (прочитать перед началом)

- Спека: `docs/superpowers/specs/2026-06-01-p2p-gui-wiring-design.md`.
- **Колбэк P2P отличается от «Центра».** `P2PService.on_message` отдаёт
  `(conversation_id: int, body: bytes)` (см. `tests/test_e2e_p2p.py`:
  `on_message=lambda _cid, body: ...`). У «Центра» — `(conversation_id, local_id)`.
  Сервис сам персистит входящее в vault до вызова колбэка; UI лишь перечитывает
  историю по `conversation_id`.
- `P2PService(vault, rendezvous_url, *, on_message, on_state_change, on_error,
  connect_timeout=10.0, punch_timeout=1.0, allow_direct=True)`; публичные методы:
  `start()`, `stop()`, `start_session(phrase, *, timeout=None) -> int`,
  `send(cid, text, *, timeout=15.0)`, `has_session(cid) -> bool`,
  `role_of(cid) -> Role | None`.
- `RendezvousClient` ждёт полный WS-URL (`ws://…`/`wss://…`).
- Тесты: headless Qt уже включён в `tests/conftest.py`
  (`QT_QPA_PLATFORM=offscreen`). KDF для тестов:
  `FAST = {"time_cost": 1, "memory_cost": 8, "parallelism": 1}`.
- **Запуск тестов в этом Nix-окружении** требует libsodium на пути линковщика:
  `export LD_LIBRARY_PATH=$(dirname "$(find /nix/store -maxdepth 3 -name 'libsodium.so.26' | head -1)")`
  Все команды `pytest` ниже подразумевают, что эта переменная уже выставлена.
- Запуск всего набора: `.venv/bin/python -m pytest -q`.

## Структура файлов

- Modify: `src/mys_ui/dialogs/phrase.py` — добавить поле rendezvous + `rendezvous_url()`.
- Modify: `src/mys_ui/controller.py` — `p2p_factory`, `ensure_p2p_service`,
  p2p-наблюдатели, маршрутизация `create_conversation`, остановка в `lock()`.
- Modify: `src/mys_ui/app.py` — боевая фабрика `_p2p_factory`.
- Modify: `src/mys_ui/windows/main_window.py` — `_P2PBridge`, регистрация
  наблюдателя, worker-поток старта, слоты.
- Create: `scripts/run_rendezvous.py` — LAN-runner встроенного сервера.
- Modify: `scripts/README.md` — инструкция LAN-прогона.
- Create: `tests/test_ui_phrase_dialog.py` — юнит диалога.
- Create: `tests/test_p2p_gui_wiring.py` — интеграция двух контроллеров.
- Modify: `tests/test_ui_controller.py` — юниты ленивого сервиса (fake).

---

## Task 1: PhraseDialog — поле rendezvous

**Files:**
- Modify: `src/mys_ui/dialogs/phrase.py`
- Test: `tests/test_ui_phrase_dialog.py` (create)

- [ ] **Step 1: Написать падающий тест**

Create `tests/test_ui_phrase_dialog.py`:

```python
from mys_ui.dialogs.phrase import DEFAULT_RENDEZVOUS, PhraseDialog


def test_default_rendezvous_url(qtbot):
    d = PhraseDialog()
    qtbot.addWidget(d)
    assert d.rendezvous_url() == DEFAULT_RENDEZVOUS
    assert DEFAULT_RENDEZVOUS == "wss://soufos.ru/p2p"


def test_returns_phrase_and_rendezvous_stripped(qtbot):
    d = PhraseDialog()
    qtbot.addWidget(d)
    d.field.setText("  секрет  ")
    d.rendezvous.setText("  ws://10.0.0.5:8765/p2p  ")
    assert d.phrase() == "секрет"
    assert d.rendezvous_url() == "ws://10.0.0.5:8765/p2p"
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `.venv/bin/python -m pytest tests/test_ui_phrase_dialog.py -q`
Expected: FAIL — `ImportError: cannot import name 'DEFAULT_RENDEZVOUS'`.

- [ ] **Step 3: Реализовать**

Replace the full contents of `src/mys_ui/dialogs/phrase.py`:

```python
"""Ввод общей секретной фразы и адреса rendezvous для P2P-режима."""

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

DEFAULT_RENDEZVOUS = "wss://soufos.ru/p2p"


class PhraseDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Секретная фраза")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Общая секретная фраза (P2P):"))
        self.field = QLineEdit()
        layout.addWidget(self.field)
        layout.addWidget(QLabel("Rendezvous:"))
        self.rendezvous = QLineEdit(DEFAULT_RENDEZVOUS)
        layout.addWidget(self.rendezvous)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def phrase(self) -> str:
        return self.field.text().strip()

    def rendezvous_url(self) -> str:
        return self.rendezvous.text().strip()
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `.venv/bin/python -m pytest tests/test_ui_phrase_dialog.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/mys_ui/dialogs/phrase.py tests/test_ui_phrase_dialog.py
git commit -m "feat(p2p): поле rendezvous в диалоге фразы"
```

---

## Task 2: Контроллер — ленивый P2P-сервис

**Files:**
- Modify: `src/mys_ui/controller.py`
- Test: `tests/test_ui_controller.py`

- [ ] **Step 1: Написать падающий тест**

Append to `tests/test_ui_controller.py`:

```python
from mys_ui.controller import DECENTRALIZED


class _FakeP2P:
    """Фейковый P2P-сервис: фиксирует жизненный цикл без сети."""

    def __init__(self, vault, rendezvous_url, *, on_message, on_state_change, on_error):
        self.vault = vault
        self.url = rendezvous_url
        self.on_message = on_message
        self.started = False
        self.stopped = False
        self.sessions: dict[int, str] = {}

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def start_session(self, phrase, *, timeout=None):
        cid = len(self.sessions) + 1
        self.sessions[cid] = phrase
        return cid

    def has_session(self, cid):
        return cid in self.sessions


def _p2p_ready(tmp_path):
    built: list[_FakeP2P] = []

    def factory(vault, rendezvous_url, **cb):
        svc = _FakeP2P(vault, rendezvous_url, **cb)
        built.append(svc)
        return svc

    c = AppController(str(tmp_path / "v.db"), kdf_params=FAST, p2p_factory=factory)
    c.create_vault(b"pw")
    c.set_mode(DECENTRALIZED)
    return c, built


def test_ensure_p2p_service_builds_and_starts(tmp_path):
    c, built = _p2p_ready(tmp_path)
    svc = c.ensure_p2p_service("ws://a:1/p2p")
    assert built == [svc]
    assert svc.started is True
    assert svc.url == "ws://a:1/p2p"


def test_ensure_p2p_service_reuses_same_url(tmp_path):
    c, built = _p2p_ready(tmp_path)
    s1 = c.ensure_p2p_service("ws://a:1/p2p")
    s2 = c.ensure_p2p_service("ws://a:1/p2p")
    assert s1 is s2
    assert len(built) == 1


def test_ensure_p2p_service_switches_url_stops_old(tmp_path):
    c, built = _p2p_ready(tmp_path)
    s1 = c.ensure_p2p_service("ws://a:1/p2p")
    s2 = c.ensure_p2p_service("ws://b:2/p2p")
    assert s1.stopped is True
    assert s2 is not s1
    assert len(built) == 2


def test_create_conversation_routes_to_start_session(tmp_path):
    c, built = _p2p_ready(tmp_path)
    cid = c.create_conversation(
        "фраза", room_phrase="общая фраза", rendezvous_url="ws://a:1/p2p"
    )
    assert built[0].sessions[cid] == "общая фраза"


def test_lock_stops_p2p_service(tmp_path):
    c, built = _p2p_ready(tmp_path)
    svc = c.ensure_p2p_service("ws://a:1/p2p")
    c.lock()
    assert svc.stopped is True


def test_p2p_observer_receives_message(tmp_path):
    c, _ = _p2p_ready(tmp_path)
    seen: list[tuple] = []
    c.add_p2p_observer(
        on_message=lambda cid, body: seen.append((cid, body)),
        on_state_change=None,
        on_error=None,
    )
    c._p2p_on_message(7, b"hi")
    assert seen == [(7, b"hi")]
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `.venv/bin/python -m pytest tests/test_ui_controller.py -q`
Expected: FAIL — `TypeError: AppController.__init__() got an unexpected keyword argument 'p2p_factory'`.

- [ ] **Step 3: Реализовать — конструктор и наблюдатели**

In `src/mys_ui/controller.py`, change `__init__` signature and body. Replace:

```python
    def __init__(
        self,
        vault_path: str | None = None,
        *,
        kdf_params: dict | None = None,
        central_factory=None,
    ):
        self._path = vault_path or paths.default_vault_path()
        self._kdf = kdf_params
        self.vault: Vault | None = None
        self.mode: str = DECENTRALIZED
        # P2P-сервис (mys_decentralized.P2PService) подключается извне; без него
        # децентрализованный режим работает как локальная заглушка (нет сети).
        self._service = None
        # Централизованный сервис создаётся лениво при первом входе фабрикой
        # central_factory(vault, *, on_message, on_state_change, on_error).
        self._central_factory = central_factory
        self._central = None
        self._central_observers: list[dict] = []
```

with:

```python
    def __init__(
        self,
        vault_path: str | None = None,
        *,
        kdf_params: dict | None = None,
        central_factory=None,
        p2p_factory=None,
    ):
        self._path = vault_path or paths.default_vault_path()
        self._kdf = kdf_params
        self.vault: Vault | None = None
        self.mode: str = DECENTRALIZED
        # P2P-сервис создаётся лениво фабрикой p2p_factory(vault, rendezvous_url,
        # *, on_message, on_state_change, on_error) при первом подключении по фразе;
        # без фабрики децентрализованный режим — локальная заглушка (нет сети).
        self._service = None
        self._p2p_factory = p2p_factory
        self._p2p_rendezvous_url: str | None = None
        self._p2p_observers: list[dict] = []
        # Централизованный сервис создаётся лениво при первом входе фабрикой
        # central_factory(vault, *, on_message, on_state_change, on_error).
        self._central_factory = central_factory
        self._central = None
        self._central_observers: list[dict] = []
```

- [ ] **Step 4: Реализовать — ensure/observers/notify**

In `src/mys_ui/controller.py`, replace the `attach_service` method:

```python
    def attach_service(self, service) -> None:
        """Подключить P2P-сервис для децентрализованного режима."""
        self._service = service
```

with:

```python
    def attach_service(self, service) -> None:
        """Подключить готовый P2P-сервис (тесты/ручное подключение без фабрики)."""
        self._service = service

    def p2p_available(self) -> bool:
        """Сконфигурирован ли P2P (есть фабрика)."""
        return self._p2p_factory is not None

    def add_p2p_observer(
        self, *, on_message=None, on_state_change=None, on_error=None
    ) -> None:
        """Подписаться на события P2P-сервиса (UI маршалит их в Qt-сигналы)."""
        self._p2p_observers.append(
            {"message": on_message, "state": on_state_change, "error": on_error}
        )

    def _notify_p2p(self, key: str, *args) -> None:
        for obs in self._p2p_observers:
            cb = obs.get(key)
            if cb is not None:
                cb(*args)

    def _p2p_on_message(self, conversation_id: int, body: bytes) -> None:
        self._notify_p2p("message", conversation_id, body)

    def _p2p_on_state(self, state) -> None:
        self._notify_p2p("state", state)

    def _p2p_on_error(self, exc: Exception) -> None:
        self._notify_p2p("error", exc)

    def ensure_p2p_service(self, rendezvous_url: str):
        """Поднять (или переключить) единственный P2P-сервис на данный rendezvous.

        Тот же URL → переиспользуем; другой URL → останавливаем старый и строим
        новый фабрикой. Колбэки сервиса уходят в p2p-наблюдателей."""
        if self._p2p_factory is None:
            raise RuntimeError("P2P-сервис не сконфигурирован")
        if self._service is not None and self._p2p_rendezvous_url == rendezvous_url:
            return self._service
        if self._service is not None:
            self._service.stop()
            self._service = None
            self._p2p_rendezvous_url = None
        svc = self._p2p_factory(
            self.vault,
            rendezvous_url,
            on_message=self._p2p_on_message,
            on_state_change=self._p2p_on_state,
            on_error=self._p2p_on_error,
        )
        svc.start()
        self._service = svc
        self._p2p_rendezvous_url = rendezvous_url
        return svc
```

- [ ] **Step 5: Реализовать — маршрутизация create_conversation**

In `src/mys_ui/controller.py`, replace the `create_conversation` method:

```python
    def create_conversation(self, title: str, *, room_phrase: str | None = None) -> int:
        # В децентрализованном режиме с фразой и подключённым сервисом — реальная
        # P2P-сессия (фраза → PAKE → канал); беседа создаётся/находится по room_id.
        # Иначе (нет сети/фразы) — локальная заглушка.
        if self.mode == DECENTRALIZED and room_phrase and self._service is not None:
            return self._service.start_session(room_phrase)
        # Централизованный режим с активной сессией — реальная серверная комната
        # (создаётся на сервере, синкается в локальную беседу). Иначе — заглушка.
        if (
            self.mode == CENTRALIZED
            and self._central is not None
            and self._central.session is not None
        ):
            return self._central.create_room(title)
        return self.vault.conversations.add(mode=self.mode, title=title)
```

with:

```python
    def create_conversation(
        self,
        title: str,
        *,
        room_phrase: str | None = None,
        rendezvous_url: str | None = None,
    ) -> int:
        # Децентрализованный режим с фразой: фабрика → поднять/переключить сервис на
        # указанный rendezvous → start_session (фраза → PAKE → канал). Если сервис
        # подключён напрямую (attach_service, без фабрики) — используем его.
        # Иначе (нет сети/фразы) — локальная заглушка.
        if self.mode == DECENTRALIZED and room_phrase:
            if self._p2p_factory is not None and rendezvous_url:
                self.ensure_p2p_service(rendezvous_url)
            if self._service is not None:
                return self._service.start_session(room_phrase)
        # Централизованный режим с активной сессией — реальная серверная комната
        # (создаётся на сервере, синкается в локальную беседу). Иначе — заглушка.
        if (
            self.mode == CENTRALIZED
            and self._central is not None
            and self._central.session is not None
        ):
            return self._central.create_room(title)
        return self.vault.conversations.add(mode=self.mode, title=title)
```

- [ ] **Step 6: Реализовать — остановка в lock()**

In `src/mys_ui/controller.py`, replace the `lock` method:

```python
    def lock(self) -> None:
        if self._central is not None:
            self._central.stop()  # остановить фоновый loop до закрытия vault
            self._central = None
        if self.vault is not None:
            self.vault.close()
            self.vault = None
```

with:

```python
    def lock(self) -> None:
        if self._service is not None:
            self._service.stop()  # остановить P2P-поток/сокет до закрытия vault
            self._service = None
            self._p2p_rendezvous_url = None
        if self._central is not None:
            self._central.stop()  # остановить фоновый loop до закрытия vault
            self._central = None
        if self.vault is not None:
            self.vault.close()
            self.vault = None
```

- [ ] **Step 7: Запустить — убедиться, что проходит**

Run: `.venv/bin/python -m pytest tests/test_ui_controller.py -q`
Expected: PASS (все прежние + 6 новых).

- [ ] **Step 8: Commit**

```bash
git add src/mys_ui/controller.py tests/test_ui_controller.py
git commit -m "feat(p2p): ленивый жизненный цикл P2P-сервиса в контроллере"
```

---

## Task 3: app.py — боевая фабрика P2P

**Files:**
- Modify: `src/mys_ui/app.py`
- Test: `tests/test_p2p_gui_wiring.py` (create — первый тест файла)

- [ ] **Step 1: Написать падающий тест**

Create `tests/test_p2p_gui_wiring.py`:

```python
"""Проводка P2P в GUI: боевая фабрика + интеграция двух контроллеров."""

import asyncio

import pytest

from mys_decentralized import P2PService, RendezvousServer
from mys_decentralized.protocol import Role
from mys_storage import create_vault
from mys_ui.app import _p2p_factory
from mys_ui.controller import AppController, DECENTRALIZED

FAST = {"time_cost": 1, "memory_cost": 8, "parallelism": 1}


def test_p2p_factory_builds_service(tmp_path):
    vault = create_vault(str(tmp_path / "v.db"), b"pw", params=FAST)
    svc = _p2p_factory(
        vault,
        "ws://127.0.0.1:1/p2p",
        on_message=None,
        on_state_change=None,
        on_error=None,
    )
    assert isinstance(svc, P2PService)
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `.venv/bin/python -m pytest tests/test_p2p_gui_wiring.py::test_p2p_factory_builds_service -q`
Expected: FAIL — `ImportError: cannot import name '_p2p_factory' from 'mys_ui.app'`.

- [ ] **Step 3: Реализовать**

In `src/mys_ui/app.py`, add import near the existing `from mys_centralized import CentralizedService`:

```python
from mys_decentralized import P2PService
```

Add the factory after `_central_factory`:

```python
def _p2p_factory(vault, rendezvous_url, *, on_message, on_state_change, on_error):
    """Боевая фабрика P2P: rendezvous-URL приходит из диалога фразы."""
    return P2PService(
        vault,
        rendezvous_url,
        on_message=on_message,
        on_state_change=on_state_change,
        on_error=on_error,
    )
```

Change the controller construction in `main()`:

```python
    shell = AppShell(AppController(central_factory=_central_factory))
```

to:

```python
    shell = AppShell(
        AppController(central_factory=_central_factory, p2p_factory=_p2p_factory)
    )
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `.venv/bin/python -m pytest tests/test_p2p_gui_wiring.py::test_p2p_factory_builds_service -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mys_ui/app.py tests/test_p2p_gui_wiring.py
git commit -m "feat(p2p): боевая фабрика P2PService в app.py"
```

---

## Task 4: MainWindow — мост, worker-старт, слоты

**Files:**
- Modify: `src/mys_ui/windows/main_window.py`
- Test: `tests/test_ui_main_window.py`

- [ ] **Step 1: Написать падающий тест**

Append to `tests/test_ui_main_window.py`:

```python
class _FakeP2PSvc:
    def __init__(self, vault, rendezvous_url, *, on_message, on_state_change, on_error):
        self.on_message = on_message
        self.started = False
        self.stopped = False
        self.sessions: dict[int, str] = {}

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def start_session(self, phrase, *, timeout=None):
        cid = len(self.sessions) + 1
        self.sessions[cid] = phrase
        return cid

    def has_session(self, cid):
        return cid in self.sessions


def _p2p_window(tmp_path):
    c = AppController(
        str(tmp_path / "v.db"), kdf_params=FAST, p2p_factory=_FakeP2PSvc
    )
    c.create_vault(b"pw")
    c.set_mode(DECENTRALIZED)
    return c


def test_p2p_connect_worker_creates_conversation(qtbot, tmp_path):
    c = _p2p_window(tmp_path)
    w = MainWindow(c)
    qtbot.addWidget(w)
    with qtbot.waitSignal(w._p2p_bridge.started, timeout=2000) as blocker:
        w._p2p_connect_worker("общая фраза", "ws://a:1/p2p")
    assert blocker.args == [True, ""]
    assert len(c.list_conversations()) == 1
    c.lock()


def test_p2p_connect_worker_reports_failure(qtbot, tmp_path, monkeypatch):
    c = _p2p_window(tmp_path)
    w = MainWindow(c)
    qtbot.addWidget(w)

    def boom(*a, **k):
        raise RuntimeError("нет связи")

    monkeypatch.setattr(c, "create_conversation", boom)
    with qtbot.waitSignal(w._p2p_bridge.started, timeout=2000) as blocker:
        w._p2p_connect_worker("ф", "ws://a:1/p2p")
    assert blocker.args[0] is False
    assert "нет связи" in blocker.args[1]
    c.lock()


def test_p2p_incoming_message_refreshes(qtbot, tmp_path):
    c = _p2p_window(tmp_path)
    w = MainWindow(c)
    qtbot.addWidget(w)
    # Поднять сервис и сессию, выбрать беседу.
    cid = c.create_conversation(
        "ф", room_phrase="общая фраза", rendezvous_url="ws://a:1/p2p"
    )
    # Положить входящее в vault, как сделал бы сервис, затем дёрнуть колбэк.
    c.vault.messages.add(cid, direction="in", body=b"пинг", status="received")
    w._on_select(cid)
    before = w.chat.count()
    with qtbot.waitSignal(w._p2p_bridge.message, timeout=2000):
        c._p2p_on_message(cid, b"пинг")
    assert w.chat.count() >= before
    c.lock()
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `.venv/bin/python -m pytest tests/test_ui_main_window.py -q -k p2p`
Expected: FAIL — `AttributeError: 'MainWindow' object has no attribute '_p2p_bridge'`.

- [ ] **Step 3: Реализовать — мост-класс**

In `src/mys_ui/windows/main_window.py`, add a bridge class after `_CentralBridge`:

```python
class _P2PBridge(QObject):
    """Мост из потока P2P-сервиса в UI-поток через Qt-сигналы."""

    message = Signal(int)
    state = Signal(str)
    error = Signal(str)
    started = Signal(bool, str)
```

- [ ] **Step 4: Реализовать — регистрация в __init__**

In `MainWindow.__init__`, right after the existing central-bridge block
(the `self._c.add_central_observer(...)` call, before `self.refresh_conversations()`),
add:

```python
        # Мост real-time P2P-режима.
        self._p2p_bridge = _P2PBridge()
        self._p2p_bridge.message.connect(self._on_p2p_message)
        self._p2p_bridge.state.connect(self._on_p2p_state)
        self._p2p_bridge.error.connect(self._on_p2p_error)
        self._p2p_bridge.started.connect(self._on_p2p_started)
        self._c.add_p2p_observer(
            on_message=lambda cid, _body: self._p2p_bridge.message.emit(cid),
            on_state_change=lambda st: self._p2p_bridge.state.emit(str(st)),
            on_error=lambda exc: self._p2p_bridge.error.emit(str(exc)),
        )
        self._p2p_state: str | None = None
        self._p2p_error: str | None = None
```

- [ ] **Step 5: Реализовать — worker-старт в _on_new**

In `src/mys_ui/windows/main_window.py`, replace the `_on_new` method:

```python
    def _on_new(self) -> None:
        if self._c.mode == DECENTRALIZED:
            dialog = PhraseDialog(self)
            if dialog.exec() == QDialog.Accepted and dialog.phrase():
                self.add_conversation(dialog.phrase(), room_phrase=dialog.phrase())
        else:
            title, ok = QInputDialog.getText(self, "Новый диалог", "Название:")
            if ok and title:
                self.add_conversation(title)
```

with:

```python
    def _on_new(self) -> None:
        if self._c.mode == DECENTRALIZED:
            dialog = PhraseDialog(self)
            if dialog.exec() == QDialog.Accepted and dialog.phrase():
                phrase = dialog.phrase()
                url = dialog.rendezvous_url()
                # start_session блокирует до connect_timeout (≈10с) — в worker-поток,
                # чтобы не заморозить UI; результат вернётся сигналом started.
                threading.Thread(
                    target=self._p2p_connect_worker,
                    args=(phrase, url),
                    name="mys-p2p-connect",
                    daemon=True,
                ).start()
        else:
            title, ok = QInputDialog.getText(self, "Новый диалог", "Название:")
            if ok and title:
                self.add_conversation(title)
```

- [ ] **Step 6: Реализовать — worker и P2P-слоты**

In `src/mys_ui/windows/main_window.py`, add these methods (place after the
central real-time slots, before `_open_settings`):

```python
    # --- real-time P2P-режима ---------------------------------------------------

    def _p2p_connect_worker(self, phrase: str, rendezvous_url: str) -> None:
        """Фоновый поток: поднять сервис и сессию; результат — сигналом в UI."""
        ok, msg = True, ""
        try:
            self._c.create_conversation(
                phrase, room_phrase=phrase, rendezvous_url=rendezvous_url
            )
        except Exception as exc:  # коннект/PAKE/таймаут/транспорт
            ok, msg = False, str(exc)
        self._p2p_bridge.started.emit(ok, msg)

    def _on_p2p_started(self, ok: bool, message: str) -> None:
        if ok:
            self.refresh_conversations()
        else:
            QMessageBox.warning(
                self, "P2P: соединение не установлено", message or "Ошибка"
            )

    def _on_p2p_message(self, conversation_id: int) -> None:
        self.refresh_conversations()
        if conversation_id == self._current:
            self.chat.show_messages(self._c.list_messages(conversation_id))

    def _on_p2p_state(self, state: str) -> None:
        self._p2p_state = state

    def _on_p2p_error(self, message: str) -> None:
        self._p2p_error = message
```

- [ ] **Step 7: Запустить — убедиться, что проходит**

Run: `.venv/bin/python -m pytest tests/test_ui_main_window.py -q`
Expected: PASS (прежние + 3 новых p2p-теста).

- [ ] **Step 8: Commit**

```bash
git add src/mys_ui/windows/main_window.py tests/test_ui_main_window.py
git commit -m "feat(p2p): мост колбэков и неблокирующий старт P2P в главном окне"
```

---

## Task 5: Интеграция — два контроллера через встроенный rendezvous

**Files:**
- Modify: `tests/test_p2p_gui_wiring.py`

- [ ] **Step 1: Написать тест**

Append to `tests/test_p2p_gui_wiring.py`:

```python
async def _start_server() -> tuple[RendezvousServer, str]:
    server = RendezvousServer()
    host, port = await server.start("127.0.0.1", 0)
    return server, f"ws://{host}:{port}/p2p"


async def _wait_for(pred, timeout: float = 5.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if pred():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("условие не выполнено за таймаут")


def _test_factory(vault, rendezvous_url, *, on_message, on_state_change, on_error):
    # Тестовая фабрика: без прямого hole-punch, короткий таймаут коннекта.
    return P2PService(
        vault,
        rendezvous_url,
        allow_direct=False,
        connect_timeout=3,
        on_message=on_message,
        on_state_change=on_state_change,
        on_error=on_error,
    )


async def test_two_controllers_exchange_message(tmp_path):
    """Два AppController через встроенный rendezvous: проводка фабрика→ensure→
    start_session→on_message, обмен одним сообщением от INITIATOR к RESPONDER."""
    server, url = await _start_server()
    recv_a: list[bytes] = []
    recv_b: list[bytes] = []

    ca = AppController(str(tmp_path / "a.db"), kdf_params=FAST, p2p_factory=_test_factory)
    cb = AppController(str(tmp_path / "b.db"), kdf_params=FAST, p2p_factory=_test_factory)
    ca.create_vault(b"pw-a")
    cb.create_vault(b"pw-b")
    ca.set_mode(DECENTRALIZED)
    cb.set_mode(DECENTRALIZED)
    ca.add_p2p_observer(
        on_message=lambda cid, body: recv_a.append(body),
        on_state_change=None,
        on_error=None,
    )
    cb.add_p2p_observer(
        on_message=lambda cid, body: recv_b.append(body),
        on_state_change=None,
        on_error=None,
    )
    try:
        phrase = "общая фраза для проводки gui"
        conv_a, conv_b = await asyncio.gather(
            asyncio.to_thread(
                ca.create_conversation, phrase, room_phrase=phrase, rendezvous_url=url
            ),
            asyncio.to_thread(
                cb.create_conversation, phrase, room_phrase=phrase, rendezvous_url=url
            ),
        )
        # Первым в Double Ratchet шлёт INITIATOR; определяем сторону по роли.
        if ca._service.role_of(conv_a) == Role.INITIATOR:
            sender, sconv, inbox = ca, conv_a, recv_b
        else:
            sender, sconv, inbox = cb, conv_b, recv_a
        await asyncio.to_thread(sender.send_message, sconv, "привет из gui")
        await _wait_for(lambda: inbox)
        assert inbox[0] == "привет из gui".encode("utf-8")
    finally:
        ca.lock()
        cb.lock()
        await server.stop()
```

- [ ] **Step 2: Запустить — убедиться, что проходит**

Run: `.venv/bin/python -m pytest tests/test_p2p_gui_wiring.py -q`
Expected: PASS (2 passed: factory + интеграция).

Если тест зависает — проверь, что `LD_LIBRARY_PATH` указывает на libsodium
(CPace грузится через ctypes); без него хендшейк не стартует.

- [ ] **Step 3: Commit**

```bash
git add tests/test_p2p_gui_wiring.py
git commit -m "test(p2p): интеграция двух контроллеров через встроенный rendezvous"
```

---

## Task 6: LAN-runner и инструкция

**Files:**
- Create: `scripts/run_rendezvous.py`
- Modify: `scripts/README.md`

- [ ] **Step 1: Создать runner**

Create `scripts/run_rendezvous.py`:

```python
#!/usr/bin/env python3
"""Запуск встроенного rendezvous-сервера на сети для LAN-проверки P2P.

Один из компьютеров (или любой в той же подсети) запускает этот скрипт; обе
машины вписывают напечатанный URL в поле «Rendezvous:» диалога фразы.

Пример:
    LD_LIBRARY_PATH=<libsodium_dir> .venv/bin/python scripts/run_rendezvous.py --port 8765
"""

import argparse
import asyncio
import socket

from mys_decentralized import RendezvousServer


def _lan_ip() -> str:
    """Локальный IP в сторону внешней сети (без реальной отправки пакетов)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


async def _main(host: str, port: int) -> None:
    server = RendezvousServer()
    bound_host, bound_port = await server.start(host, port)
    lan = _lan_ip()
    print(f"Rendezvous слушает на {bound_host}:{bound_port}")
    print(f"Вписать на обеих машинах:  ws://{lan}:{bound_port}/p2p")
    print("Ctrl-C для остановки.")
    try:
        await asyncio.Future()  # работать до прерывания
    finally:
        await server.stop()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="LAN rendezvous для P2P-проверки")
    ap.add_argument("--host", default="0.0.0.0", help="адрес бинда (умолч. 0.0.0.0)")
    ap.add_argument("--port", type=int, default=8765, help="порт (умолч. 8765)")
    args = ap.parse_args()
    try:
        asyncio.run(_main(args.host, args.port))
    except KeyboardInterrupt:
        pass
```

- [ ] **Step 2: Проверить запуск runner'а**

Run (с таймаутом, чтобы оборвать):
`timeout 2 .venv/bin/python scripts/run_rendezvous.py --port 8765 || true`
Expected: печатает `Rendezvous слушает на 0.0.0.0:8765` и
`Вписать на обеих машинах:  ws://<lan-ip>:8765/p2p`, затем завершается по timeout.

- [ ] **Step 3: Дополнить README**

In `scripts/README.md`, append a section:

```markdown
## LAN-проверка P2P (run_rendezvous.py)

Для ручной проверки децентрализованного режима между двумя машинами в локалке:

1. На одной из машин (или любой в той же подсети) запустить rendezvous:
   `LD_LIBRARY_PATH=<libsodium_dir> .venv/bin/python scripts/run_rendezvous.py --port 8765`
   Скрипт напечатает `ws://<lan-ip>:8765/p2p`.
2. На обеих машинах открыть приложение, режим P2P → «+ Новый диалог»,
   ввести одинаковую секретную фразу и в поле «Rendezvous:» — напечатанный URL.
3. После хендшейка беседа появится у обоих; обмен сообщениями идёт через relay
   rendezvous-сервера.

Для проверки вне локалки в поле «Rendezvous:» вписывается `wss://soufos.ru/p2p`
(боевой сервер), сам скрипт при этом не нужен.
```

- [ ] **Step 4: Commit**

```bash
git add scripts/run_rendezvous.py scripts/README.md
git commit -m "feat(p2p): LAN-runner rendezvous + инструкция в README"
```

---

## Task 7: Полный прогон и ручная проверка

- [ ] **Step 1: Прогнать весь набор тестов**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS — прежние ~172 теста + новые (PhraseDialog 2, контроллер 6,
main_window 3, проводка 2). Ни один не упал.

- [ ] **Step 2: Ручной smoke на одной машине (loopback)**

В одном терминале запустить rendezvous:
`.venv/bin/python scripts/run_rendezvous.py --port 8765`
В двух других — два экземпляра приложения с разными vault-файлами (см.
`src/mys_ui/paths.py` про путь к vault; при отсутствии переопределения запускать
второй экземпляр под другим $HOME). В обоих: режим P2P → «+ Новый диалог» →
одинаковая фраза + `ws://127.0.0.1:8765/p2p`. Ожидание: беседа появляется у обоих,
сообщения ходят в обе стороны.

- [ ] **Step 3: Отметить готовность**

При необходимости зафиксировать в `CLAUDE.md`/спеке отметку о готовности
проводки P2P в GUI и снять соответствующий follow-up этапа №7.

---

## Self-review (для исполнителя)

- Все колбэки P2P маршалятся через `_P2PBridge` (UI-поток) — прямых обращений к
  виджетам из потока сервиса нет.
- `lock()` глушит P2P-сервис до закрытия vault — нет висящих потоков.
- `start_session` вызывается только из worker-потока (`_p2p_connect_worker`).
- Боевой `wss://soufos.ru/p2p` — следующий шаг ручной проверки после зелёного LAN
  (за рамками автотестов; зависит от серверного `/p2p` в `vsc_web`).
