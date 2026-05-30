# Децентрализованный модуль (mys_decentralized) — спецификация

**Дата:** 2026-05-30
**Статус:** черновик (фаза дизайна под-проекта №4)
**Контекст:** под-проект №4 из `docs/superpowers/specs/2026-05-29-mys-desktop-design.md`
(раздел 3 — децентрализованный модуль; раздел 5 — поток децентрализованной
сессии). Зависит от крипто-ядра `mys_crypto` (№1, готов) и хранилища
`mys_storage` (№2, готов). Поверх него работает UI-каркас `mys_ui` (№3, готов),
где сейчас стоят заглушки P2P. Серверная часть (реальный rendezvous+relay в
`vsc_web`) — отдельный под-проект №5; здесь поднимается **тестовый/референсный**
сервер.

## 1. Цель и границы

Анонимный **P2P-чат 1:1, только онлайн**: два пользователя вводят общую
секретную фразу и получают сквозь-шифрованный канал без аккаунтов и без
доверия к серверу. Реализуем полный поток из раздела 5 дизайна:

1. фраза → `room_id` (сервер фразу не видит);
2. rendezvous: сведение двух пиров в «комнату», обмен кандидатами/ролями;
3. установка транспорта: **relay-first** (рабочий путь через сервер) + каркас
   UDP hole-punch как альтернативный путь с fallback на relay;
4. PAKE (**CPace**) по фразе поверх транспорта → взаимная аутентификация +
   сессионный ключ, защита от MITM;
5. Double Ratchet поверх канала, каждое сообщение → AEAD + МЫС-transform
   (`mys_crypto.envelope.seal/open`);
6. приём/отправка с записью в локальный зашифрованный vault.

### Что входит в №4
- Примитив **CPace** (Ristretto255) в крипто-ядре — чистые функции, TDD с
  тест-векторами CFRG-черновика.
- Пакет `src/mys_decentralized/`: derivation `room_id`, wire-протокол и фрейминг,
  rendezvous-клиент, транспорт (relay + hole-punch каркас), PAKE-хендшейк поверх
  транспорта, защищённая сессия (ratchet+envelope+персист), asyncio-оркестрация
  и потокобезопасный мост для контроллера.
- **Тестовый rendezvous-сервер** (`asyncio`) — для интеграционных тестов и как
  референс для реальной реализации в `vsc_web` (№5).
- Включение реального P2P в `mys_ui.AppController` вместо текущих заглушек.

### Что НЕ входит (отложено)
- Реальный серверный rendezvous+relay в `vsc_web` — под-проект №5.
- Групповые P2P, оффлайн-доставка (store-and-forward), передача файлов — за v1.
- Полноценный STUN/TURN и обход симметричных NAT — каркас hole-punch не зависит
  от живого STUN; продакшен-NAT-логика дорабатывается позже.

### Границы модулей (CLAUDE.md, соблюдать строго)
- **Крипто не знает о сети.** CPace — чистые функции над байтами/точками,
  выдают `ISK`/`sk`; ни сокетов, ни I/O.
- **Сеть не знает деталей шифрования.** Rendezvous и транспорт оперируют
  **непрозрачными фреймами** (`bytes`), не знают про ratchet/AEAD. Сборку
  «защищённого канала» делает слой `session` поверх готового транспорта.
- **UI не знает ни крипто, ни сети.** Доступ только через `AppController`,
  который не импортирует Qt и общается с сетью через мост `service`.
- Хранилище уже изолировано; модуль пишет через существующий
  `Vault.receive_message(...)` и `messages`/`conversations`/`ratchet` репозитории.

## 2. Стек и зависимости

- **Сеть:** стандартный `asyncio` (UDP `DatagramProtocol`, TCP streams для relay).
- **CPace:** Ristretto255 через **PyNaCl** (libsodium): `crypto_core_ristretto255_from_hash`,
  `crypto_scalarmult_ristretto255`, скалярная арифметика. Причина — `cryptography`
  не даёт hash-to-group и операций над произвольными точками; libsodium даёт
  безопасный Ristretto255, ровно под ciphersuite CPace-ristretto255.
- **Хеши:** `hashlib` (SHA-512 для map-to-group, SHA-256 для transcript/HKDF).
- **Крипто-склейка:** `mys_crypto` (`primitives.hkdf`, `ratchet`, `envelope`).
- **Тесты:** `pytest`, `pytest-asyncio` для асинхронных путей.

Добавляются в `pyproject.toml`: `PyNaCl>=1.5`, `pytest-asyncio` (dev).
Новый пакет `src/mys_decentralized/`.

## 3. Деривация room_id и параметры PAKE

Из секретной фразы выводятся **независимые** значения, чтобы сервер по `room_id`
не мог восстановить фразу или вести себя как оракул для PAKE:

```
norm     = NFKC(phrase).strip()           # нормализация ввода
seed     = BLAKE2b-256(norm, person=b"mys-phrase")
room_id  = HKDF(seed, 32, salt=b"", info=b"mys-room-id")      # отдаётся серверу
prs      = HKDF(seed, 32, salt=b"", info=b"mys-pake-prs")      # пароль для CPace
```

- `room_id` — единственное, что видит сервер. Непрозрачен, не обратим к фразе.
- `prs` — вход CPace (Password-Related String). Не покидает клиент.
- Совпадение фраз ⇒ совпадение `room_id` ⇒ сервер сводит пиров; различие фраз
  ⇒ разные комнаты (пиры не встретятся) **или** провал CPace (если `room_id`
  случайно совпал, но `prs` различается — что вычислительно невозможно при
  разных фразах).

## 4. CPace (крипто-ядро, `mys_crypto/pake.py`)

Ciphersuite **CPace-ristretto255** (CFRG draft). Чистые функции, без сети:

- `cpace_generator(prs, sid, ci, ad) -> point_bytes` — map-to-group:
  `G = ristretto255_from_hash(SHA-512(DSI || prs || zpad || sid || ci || ad))`.
- `cpace_msg(prs, sid, ci, ad) -> (state, Y)` — генерит скаляр `y`, `Y = y·G`.
- `cpace_finish(state, Y_peer, transcript) -> ISK` — `K = y·Y_peer`,
  `ISK = SHA-512(DSI_isk || sid || transcript || K)`; проверка `K ≠ identity`.
- Из `ISK` слой хендшейка выводит `sk` и материал ratchet (см. §6).

**Симметрия.** CPace симметричен (balanced PAKE): обе стороны делают одно и то
же; порядок `Ya||Yb` в transcript фиксируется лексикографически, чтобы обе
стороны хешировали одинаково.

**TDD.** Тест-векторы CFRG-черновика для ristretto255 (generator, ISK), плюс:
- `cpace_finish` обеих сторон даёт **равный** ISK при равном `prs`;
- разный `prs` ⇒ разный ISK (с подавляющей вероятностью);
- отказ при `Y_peer == identity` / некорректной точке.

## 5. Wire-протокол и фрейминг (`protocol.py`)

Единый кадр поверх любого транспорта (UDP-датаграмма или TCP-сегмент после
length-prefix). Сеть трактует полезную нагрузку как **непрозрачные байты**.

```
Frame = u8 type | u8 flags | u32 length | bytes payload
```

Типы сигнализации (rendezvous, открытым текстом — не содержат секретов):
- `HELLO {room_id, candidates[]}` — клиент → сервер при входе в комнату.
- `PAIR {role, peer_candidates[]}` — сервер → клиенту: роль и адреса пира.
- `PUNCH` / `PUNCH_ACK` — клиент↔клиент по прямому пути (hole-punch).
- `RELAY {payload}` — клиент↔сервер↔клиент: сервер пересылает payload пиру в той
  же комнате, **не читая** его.

Типы сессии (payload уже E2E-защищён или это PAKE-сообщения):
- `PAKE {Y, ad}` — сообщение CPace (открыто по дизайну PAKE, безопасно).
- `CONFIRM {mac}` — key-confirmation (MAC по transcript на `ISK`).
- `DATA {sealed}` — `envelope.seal(...)` (Header‖ct под transform).

**Роли.** Сервер назначает роли детерминированно: первый вошедший в комнату —
`initiator` (Alice в ratchet, первый в лексикографике CPace-transcript), второй —
`responder` (Bob). Это убирает неоднозначность инициализации ratchet.

## 6. Хендшейк и сборка сессии (`handshake.py`, `session.py`)

### Хендшейк (поверх готового транспорта)
1. Обе стороны строят CPace-сообщение `PAKE{Y}` и обмениваются им.
2. Каждая считает `ISK` (§4).
3. **Key-confirmation:** обмен `CONFIRM{mac}`, где
   `mac = HMAC(ISK, "mys-confirm" || transcript)`. Несовпадение ⇒ **`PAKEError`**
   (неверная фраза или MITM) → разрыв с предупреждением (дизайн §7).
4. Из `ISK` выводятся (обе стороны одинаково):
   ```
   sk          = HKDF(ISK, 32, info="mys-ratchet-root")
   bob_dh_seed = HKDF(ISK, 32, info="mys-ratchet-bob-dh")  # X25519 keypair
   ```
   Это сохраняет сигнатуры ядра без изменений: `ratchet_init_alice(sk, bob_dh_pub)`
   у initiator, `ratchet_init_bob(sk, bob_dh_keypair)` у responder — оба
   получают согласованный стартовый DH-ключ без лишних раундов. Закрывает
   follow-up «вход для ratchet» из CLAUDE.md.

### Сессия (защищённый канал)
- `transform_key = envelope.derive_transform_key(sk)`.
- Отправка: `DATA{ envelope.seal(state, transform_key, text) }`.
- Приём: `envelope.open_(state, transform_key, sealed)` → plaintext; запись
  атомарно через `Vault.receive_message(conv_id, body=..., new_state=state)`.
- Исходящее сохраняется (`messages.add(direction="out", status="sent")`) после
  успешной отправки в транспорт.
- **Персист ratchet и реконнект.** Состояние ratchet хранится per-conversation
  (по `room_id`). При обрыве сети транспорт переустанавливается, но если
  `ratchet_state` для комнаты уже существует — сессия **возобновляет** ratchet
  (PAKE на реконнекте лишь заново аутентифицирует пира и транспорт, не
  пересеивает ratchet). Первая сессия в комнате сеет ratchet из PAKE. Это
  выполняет требование дизайна §7 «реконнект с сохранением состояния ratchet».

## 7. Rendezvous и транспорт (`rendezvous.py`, `transport.py`)

### Клиент rendezvous
- Подключается к серверу, шлёт `HELLO{room_id, свои кандидаты}`.
- Получает `PAIR{role, peer_candidates}` когда второй пир вошёл; до этого ждёт
  (таймаут → `PeerUnavailable`, понятное сообщение в UI).

### Транспорт (`Transport` ABC: `async send_frame/recv_frame/close`)
**Relay-first (рабочий путь):**
- `RelayTransport` — кадры `RELAY{payload}` идут на сервер, сервер пересылает
  второму пиру в комнате. Трафик уже E2E (PAKE/DATA), сервер не читает.
- Это путь по умолчанию: гарантированно работает за любым NAT, полностью
  тестируется локально.

**Каркас hole-punch (альтернативный путь, fallback на relay):**
- `DirectTransport` (UDP) — попытка `PUNCH/PUNCH_ACK` по кандидатам из `PAIR`.
  Успех (получен `PUNCH_ACK` в таймаут) ⇒ прямой UDP-канал; иначе — `RelayTransport`.
- Каркас не зависит от живого STUN: кандидаты — локальные адреса (loopback/LAN);
  тестируется на loopback. Полная NAT-логика — позже.

### Тестовый/референсный сервер (`rendezvous_server.py`)
Минимальный `asyncio`-сервер: принимает `HELLO`, парует по `room_id`, рассылает
`PAIR`, ретранслирует `RELAY`. Без знания фразы и без чтения payload. Служит
фикстурой интеграционных тестов и образцом для реализации в `vsc_web` (№5).

## 8. Интеграция с контроллером и UI (`service.py`, правки `mys_ui`)

- **`service.py`** — `asyncio`-оркестратор P2P, запускается в отдельном фоновом
  потоке со своим event loop. Потокобезопасный API: `start_session(phrase) ->
  conv_id`, `send(conv_id, text)`, колбэки `on_message`, `on_state_change`,
  `on_error`. Без Qt.
- **`AppController`** (правки): `create_conversation(room_phrase=...)` и
  `send_message(...)` в режиме `DECENTRALIZED` идут через `service`, а не пишут
  заглушку локально. `room_id` → `conversations.add(room_id=...)`; входящие через
  `Vault.receive_message`.
- **UI** маршалит колбэки сети в Qt-сигналы (мост живёт в UI/контроллере, не в
  `mys_decentralized`). Экран ввода фразы (`dialogs/phrase.py`) запускает
  реальную сессию; провал PAKE/таймаут → понятное предупреждение.

## 9. Обработка ошибок (дизайн §7)

- Провал key-confirmation/CPace ⇒ `PAKEError` → разрыв + «неверная фраза или
  попытка перехвата».
- Пир не появился в комнате за таймаут ⇒ `PeerUnavailable`.
- Провал hole-punch ⇒ автоматический `RelayTransport` (молча, это не ошибка).
- Битый/неполный кадр, ошибка AEAD на `DATA` ⇒ кадр отбрасывается; повтор
  (replay) ⇒ ratchet/AEAD отвергает (не та позиция) — лог, без падения.
- Обрыв транспорта ⇒ переподключение с сохранением ratchet (§6).

## 10. Тестирование

- **Юнит CPace** (`test_pake.py`): тест-векторы CFRG, равенство ISK у сторон,
  расхождение при разном `prs`, отказ на identity/битой точке.
- **Юнит протокола** (`test_protocol.py`): фрейминг round-trip, деривация
  `room_id`/`prs` (детерминизм, независимость, нормализация фразы).
- **Хендшейк** (`test_handshake.py`): два локальных пира через in-memory
  транспорт → согласованный `sk`/ratchet; негатив: разные фразы → `PAKEError`;
  MITM-подмена `Y`/`CONFIRM` → `PAKEError`.
- **Транспорт/rendezvous** (`test_transport.py`, `test_rendezvous.py`): пути
  relay и direct(loopback) на тестовом сервере; пейринг по `room_id`; таймаут.
- **Сессия** (`test_session.py`): seal/open round-trip, персист и **возобновление**
  ratchet после «реконнекта», порядок сообщений, отброс битого `DATA`.
- **Интеграция** (`test_decentralized_integration.py`): два клиента через
  тестовый rendezvous обмениваются сообщениями обоими путями; данные оседают в
  двух отдельных vault’ах. Негативы: неверная фраза, MITM, битые/повторённые
  кадры.
- Async-тесты под `pytest-asyncio`; без обращений в реальную сеть.

## 11. Влияние на follow-up крипто-ядра (CLAUDE.md)

- ✅ **Вход для ratchet.** PAKE поставляет `sk` и стартовый DH-ключ (§6) —
  follow-up закрывается этим под-проектом.
- **Детерминизм transform** остаётся в силе: транспорт не полагается на transform
  против анализа трафика; защиту даёт AEAD/ratchet. Учтено в §6 (DATA несёт
  Header+ct под transform поверх AEAD).
