# Децентрализованный модуль (mys_decentralized) — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Реализовать анонимный P2P-чат 1:1 (только онлайн): фраза → `room_id` →
rendezvous → транспорт (relay-first + каркас hole-punch) → CPace-хендшейк →
Double Ratchet поверх канала → запись в зашифрованный vault. Закрыть follow-up
крипто-ядра «вход для ratchet». Спецификация:
`docs/superpowers/specs/2026-05-30-decentralized.md`.

**Architecture:** Чистый CPace (Ristretto255/PyNaCl) в крипто-ядре выдаёт `ISK`;
слой хендшейка выводит `sk` + стартовый DH-ключ и инициализирует ratchet ядра.
Сеть (rendezvous + транспорт) оперирует непрозрачными кадрами и ничего не знает о
шифровании; слой `session` собирает защищённый канал из транспорта + ratchet +
envelope и персистит состояние в vault. asyncio-оркестратор в фоновом потоке даёт
потокобезопасный API контроллеру. Тестовый rendezvous-сервер — фикстура и
референс для №5. Границы строгие (CLAUDE.md): крипто↔сеть↔UI изолированы.

**Tech Stack:** Python 3.13, `asyncio`, `PyNaCl>=1.5` (Ristretto255), `mys_crypto`,
`mys_storage`, `pytest`, `pytest-asyncio`.

---

## Структура файлов

```
src/mys_crypto/
  pake.py            # НОВОЕ: CPace-ristretto255 (чистые функции)
  __init__.py        # МОДИФ: экспорт pake
src/mys_decentralized/
  __init__.py        # публичный API
  errors.py          # PAKEError, RendezvousError, TransportError, PeerUnavailable
  protocol.py        # деривация room_id/prs, фрейминг, типы сообщений
  rendezvous.py      # async-клиент: HELLO/PAIR, ожидание пира
  rendezvous_server.py # минимальный asyncio-сервер (тест + референс №5)
  transport.py       # Transport ABC, RelayTransport, DirectTransport(hole-punch), выбор пути
  handshake.py       # CPace поверх транспорта -> sk + роль + init ratchet
  session.py         # ratchet+envelope поверх транспорта, send/recv, персист, реконнект
  service.py         # asyncio-оркестратор + потокобезопасный мост для контроллера
src/mys_ui/
  controller.py      # МОДИФ: реальный P2P в режиме DECENTRALIZED через service
tests/
  test_pake.py
  test_protocol.py
  test_handshake.py
  test_transport.py
  test_rendezvous.py
  test_session.py
  test_decentralized_integration.py
```

**Зоны ответственности:** `pake` — чистая крипто-математика, без I/O.
`protocol` — байты/деривация, без сокетов. `rendezvous`/`transport` — сеть над
непрозрачными кадрами, без крипто. `handshake`/`session` — склейка крипто+сеть.
`service` — оркестрация+мост. `controller` — единственная точка для UI.

---

### Task 1: Зависимости и каркас пакета

**Files:**
- Modify: `pyproject.toml` (добавить `PyNaCl>=1.5`; dev: `pytest-asyncio`)
- Create: `src/mys_decentralized/__init__.py`, `src/mys_decentralized/errors.py`

**Step 1: Зависимости**
- [ ] Добавить `PyNaCl>=1.5` в основные зависимости, `pytest-asyncio` в dev.
- [ ] `pip install -e .` в `.venv`; проверить импорт
      `nacl.bindings.crypto_core_ristretto255_from_hash`.

**Step 2: Каркас**
- [ ] `errors.py`: `PAKEError`, `RendezvousError`, `TransportError`,
      `PeerUnavailable` (от общего `DecentralizedError`).
- [ ] `__init__.py`: реэкспорт ошибок и (по мере готовности) публичного API.

**Verify:** `python -c "import mys_decentralized"` без ошибок; PyNaCl ristretto
доступен.

---

### Task 2 (TDD): CPace в крипто-ядре

**Files:**
- Create: `tests/test_pake.py`, `src/mys_crypto/pake.py`
- Modify: `src/mys_crypto/__init__.py`

**Step 1: Тесты (до реализации)**
- [ ] Тест-векторы CFRG ristretto255: generator из `(prs,sid,ci,ad)`, итоговый
      `ISK` — сверка с известными значениями черновика.
- [ ] Симметрия: `cpace_finish` Alice и Bob дают **равный** ISK при равном `prs`.
- [ ] Расхождение: разный `prs` ⇒ разные ISK.
- [ ] Отказ: `Y_peer == identity` или невалидная точка ⇒ исключение.

**Step 2: Реализация**
- [ ] `cpace_generator`, `cpace_msg`, `cpace_finish` через
      `crypto_core_ristretto255_from_hash` (SHA-512, 64 байта), `crypto_scalarmult_ristretto255`,
      `crypto_core_ristretto255_scalar_random`. Лексикографический порядок
      `Ya||Yb` в transcript. DSI-метки по черновику.
- [ ] Экспорт `pake` из `mys_crypto.__init__`.

**Verify:** `pytest tests/test_pake.py -q` зелёный, включая тест-векторы.

---

### Task 3 (TDD): Протокол — деривация и фрейминг

**Files:**
- Create: `tests/test_protocol.py`, `src/mys_decentralized/protocol.py`

**Step 1: Тесты**
- [ ] `derive_room_params(phrase) -> (room_id, prs)`: детерминизм; независимость
      (`room_id` не равен `prs`); нормализация (NFKC + strip ⇒ одинаковый результат
      для эквивалентных вводов); разные фразы ⇒ разные `room_id`.
- [ ] Фрейминг: `encode_frame(type, payload)`/`decode_frame` round-trip; отказ на
      усечённом кадре/несовпадении длины.
- [ ] Сериализация сообщений `HELLO/PAIR/PAKE/CONFIRM/DATA/RELAY/PUNCH`.

**Step 2: Реализация**
- [ ] `derive_room_params` по §3 спеки (BLAKE2b + HKDF, независимые `info`).
- [ ] `Frame = u8 type | u8 flags | u32 length | payload`; кодеки сообщений.

**Verify:** `pytest tests/test_protocol.py -q` зелёный.

---

### Task 4 (TDD): Хендшейк поверх транспорта

**Files:**
- Create: `tests/test_handshake.py`, `src/mys_decentralized/handshake.py`
- В тестах: in-memory дуплекс-транспорт (две связанные `asyncio.Queue`).

**Step 1: Тесты**
- [ ] Два пира (initiator/responder) через in-memory транспорт → согласованные
      `sk` и стартовый DH; `ratchet_init_alice/bob` инициализируются, первый
      `seal/open` проходит.
- [ ] Негатив: разные фразы ⇒ key-confirmation не сходится ⇒ `PAKEError`.
- [ ] MITM: подмена `Y` или `CONFIRM` атакующим ⇒ `PAKEError`.

**Step 2: Реализация**
- [ ] `async handshake(transport, prs, role) -> HandshakeResult(sk, ratchet_state)`:
      обмен `PAKE{Y}`, расчёт `ISK`, обмен `CONFIRM{mac}` (HMAC по transcript),
      вывод `sk`/`bob_dh_seed` (HKDF), init ratchet по роли (§6 спеки).

**Verify:** `pytest tests/test_handshake.py -q` зелёный; закрыт follow-up «вход
для ratchet».

---

### Task 5 (TDD): Транспорт и тестовый rendezvous-сервер

**Files:**
- Create: `tests/test_transport.py`, `tests/test_rendezvous.py`,
  `src/mys_decentralized/transport.py`, `src/mys_decentralized/rendezvous.py`,
  `src/mys_decentralized/rendezvous_server.py`

**Step 1: Тесты (pytest-asyncio)**
- [ ] Тестовый сервер: два клиента с одним `room_id` парятся, получают `PAIR`
      с ролями; разные `room_id` не парятся; таймаут ожидания пира ⇒ `PeerUnavailable`.
- [ ] `RelayTransport`: кадр от A доходит до B через сервер (сервер не читает
      payload — проверяем, что пересылает байты как есть).
- [ ] `DirectTransport` на loopback: `PUNCH/PUNCH_ACK` ⇒ прямой канал; при
      отсутствии ACK в таймаут ⇒ выбор пути падает на `RelayTransport`.

**Step 2: Реализация**
- [ ] `rendezvous_server.py`: asyncio-сервер, пейринг по `room_id`, рассылка
      `PAIR`, ретрансляция `RELAY` без чтения payload.
- [ ] `rendezvous.py`: клиент `HELLO`→ждать `PAIR` (таймаут).
- [ ] `transport.py`: `Transport` ABC; `RelayTransport`; `DirectTransport` (UDP
      `DatagramProtocol`); `establish_transport(...)` — пробует direct, fallback relay.

**Verify:** `pytest tests/test_transport.py tests/test_rendezvous.py -q` зелёный.

---

### Task 6 (TDD): Защищённая сессия + персист/реконнект

**Files:**
- Create: `tests/test_session.py`, `src/mys_decentralized/session.py`

**Step 1: Тесты**
- [ ] seal/open round-trip между двумя сессиями; порядок сообщений сохраняется.
- [ ] Персист: после «реконнекта» (новый транспорт, тот же `room_id`) сессия
      **возобновляет** ratchet из vault, сообщения продолжают расшифровываться.
- [ ] Битый `DATA` (повреждённый sealed) ⇒ отброшен, сессия жива; replay ⇒
      отвергнут ratchet/AEAD.

**Step 2: Реализация**
- [ ] `Session`: над транспортом + ratchet_state + `transform_key`; `send(text)`
      → `DATA{seal}` + `messages.add(out, sent)`; входящий `DATA` → `open_` →
      `Vault.receive_message(...)`; колбэк `on_message`.
- [ ] Загрузка/возобновление ratchet по `room_id` (ветка реконнекта по §6 спеки).

**Verify:** `pytest tests/test_session.py -q` зелёный.

---

### Task 7: Оркестратор-мост и интеграция в контроллер

**Files:**
- Create: `src/mys_decentralized/service.py`
- Modify: `src/mys_ui/controller.py`

**Step 1: service**
- [ ] asyncio event loop в фоновом потоке; потокобезопасные `start_session(phrase)`,
      `send(conv_id, text)`, `stop`; колбэки `on_message/on_state_change/on_error`
      (маршалятся вызывающим в Qt-сигналы — мост вне `mys_decentralized`).

**Step 2: controller**
- [ ] В режиме `DECENTRALIZED`: `create_conversation(room_phrase=...)` создаёт
      `conversations.add(room_id=...)` и запускает сессию; `send_message`
      отправляет через `service`. Заглушечный путь сохраняется для отсутствия сети.
- [ ] Не импортировать Qt в controller/service (как сейчас).

**Verify:** `pytest tests/test_ui_controller.py -q` остаётся зелёным; контроллер
не тянет Qt.

---

### Task 8: Интеграция, негативы и финальная проверка

**Files:**
- Create: `tests/test_decentralized_integration.py`
- Modify: `CLAUDE.md` (отметить №4 готовым, обновить follow-up «вход для ratchet»)

**Step 1: Интеграционные тесты**
- [ ] Два клиента через тестовый rendezvous обмениваются сообщениями обоими
      путями (relay и direct/loopback); данные оседают в двух отдельных vault’ах.
- [ ] Негативы: неверная фраза, MITM, битые/повторённые кадры, недоступность пира.

**Step 2: Финал**
- [ ] Весь набор тестов зелёный: `QT_QPA_PLATFORM=offscreen pytest -q`.
- [ ] `CLAUDE.md`: под-проект №4 — ✅; follow-up «вход для ratchet» — закрыт.
- [ ] Коммиты по соглашению проекта (русские, без AI-авторства).

**Verify:** полный `pytest -q` зелёный; границы модулей соблюдены (крипто/сеть/UI
изолированы); сервер не видит фразу/открытый текст.

---

## Риски и заметки

- **PyNaCl/libsodium ristretto** требует libsodium ≥1.0.18 в колесе PyNaCl —
  проверить на Task 1 импортом биндингов; при отсутствии — зафиксировать версию.
- **CPace тест-векторы:** взять из актуального CFRG-черновика; если формат DSI
  разойдётся — приоритет у самосогласованности (равный ISK у сторон) + явная
  фиксация выбранных меток в коде и тесте.
- **asyncio↔Qt:** мост строго в UI-слое; `mys_decentralized` остаётся чистым
  asyncio без Qt (тестируемость, границы CLAUDE.md).
- **Реальный сервер (№5):** `rendezvous_server.py` — референс; протокол кадров
  переносится в `vsc_web` без изменений семантики.
