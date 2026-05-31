# №7 — Стабилизация и сквозная интеграция (e2e) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Доказать, что МЫС работает целиком против **реального** сервера: реализовать в `vsc_web` серверные контракты (token+REST+`/ws` для «Центра» и rendezvous+relay `/p2p` для P2P), затем прогнать сквозные e2e-сценарии десктоп↔сервер для обоих режимов и оформить воспроизводимый smoke-скрипт.

**Architecture:** Десктоп-клиент (`mys_centralized`, `mys_decentralized`) уже написан и оттестирован против фейков под фиксированный контракт. Сервер `vsc_web` (Flask + Flask-SQLAlchemy + Flask-SocketIO + eventlet, SQLite) этих контрактов ещё не реализует. План воплощает их в `vsc_web` строго **дополнительными** маршрутами (веб-версию не ломаем), затем поднимает реальный сервер локально и гоняет против него клиента. P2P-половина e2e самодостаточна (встроенный `rendezvous_server.py`) и проверяется отдельно от `/p2p`-сервера.

**Tech Stack:** Python 3.13, Flask 3.1, Flask-SQLAlchemy, flask-sock (новое), eventlet, `websockets`, `httpx`, pytest. Десктоп: PySide6 (offscreen в тестах), libsodium через ctypes.

**Источники истины (НЕ дублируются здесь — читать оттуда эталонный код):**
- Централизованный сервер: `docs/superpowers/specs/2026-05-30-server-centralized-api.md` (§4 маппинг, §5 `bearer.py`, §6 REST-тела, §7 `ws_centralized.py`, §8 миграция, §9 регистрация, §11 тесты, §13 готовность).
- P2P-сервер: `docs/superpowers/specs/2026-05-30-server-rendezvous-relay.md` (§3 wire, §5 `rendezvous_ws.py`, §9 тесты, §10 готовность).
- Контракт клиента: `src/mys_centralized/api_client.py`, `src/mys_centralized/ws_client.py`; эталон P2P-сервера: `src/mys_decentralized/rendezvous_server.py`.

**Два репозитория.** Сервер — в `../vsc_web` (отдельный git-репозиторий, свои коммиты). Десктоп-тесты/скрипты — в `vsc_desktop`. В каждой задаче явно указано, в каком репозитории работаем.

**Окружение (важно для всех прогонов десктоп-тестов).** `.venv` уже дополнен (`pip install -e ".[dev]"`). libsodium из Nix-store не на пути линковщика — десктоп-тесты и smoke запускать с `LD_LIBRARY_PATH` на каталог libsodium. Актуальный путь искать: `find / -name 'libsodium*.so*' 2>/dev/null`. Команда прогона десктоп-тестов:
`LD_LIBRARY_PATH=<sodium_dir> QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`

---

## Структура файлов

**В `../vsc_web` (создаём):**
- `bearer.py` — выпуск/резолв opaque-токена (Bearer). Спека-центр §5.
- `centralized.py` — blueprint `central_bp` (`/api/auth/*`, `/api/rooms`, `/api/rooms/<id>/messages`, `/api/messages`). Спека-центр §6.
- `ws_centralized.py` — сырой `/ws` (flask-sock), реестр подписчиков, `fanout_message`. Спека-центр §7.
- `rendezvous_ws.py` — сырой `/p2p` (flask-sock), rendezvous+relay. Спека-p2p §5.
- `tests/test_centralized_api.py`, `tests/test_ws_centralized.py`, `tests/test_rendezvous_ws.py` — контрактные тесты (если в `vsc_web` ещё нет каталога тестов — создать + минимальный фикстурный app).

**В `../vsc_web` (модифицируем):**
- `models.py` — добавить модель `AuthToken`; колонку `Message.client_msg_id` + UNIQUE constraint.
- `app.py:89-95` — регистрация `central_bp`, `ws_bp`, `p2p` bp + `sock.init_app(app)`; `csrf.exempt(central_bp)`; миграции (§8) в `with app.app_context()` блоке рядом с существующим (`app.py:98-108`).
- `api.py` (`post_message`, ~стр.43-55) — после commit вызвать `fanout_message(room.id, {...})` (фан-аут в `/ws` и для веб-пути).
- `requirements.txt` — добавить `flask-sock`.

**В `vsc_desktop` (создаём):**
- `tests/test_e2e_p2p.py` — два локальных клиента через встроенный `rendezvous_server` (hole-punch + relay, неверная фраза, MITM, реконнект, порядок первого сообщения).
- `tests/test_e2e_centralized.py` — клиент против **реального локального** `vsc_web` (поднятого в subprocess); помечен маркером `e2e_server`, пропускается если сервер недоступен.
- `scripts/smoke.py` — поднять серверы, прогнать оба сценария, вернуть код возврата для CI.
- `scripts/README.md` — как запускать smoke локально и в CI.

**В `vsc_desktop` (модифицируем):**
- `pytest.ini` — зарегистрировать маркер `e2e_server`.
- `CLAUDE.md` — после готовности отметить №7 (или зафиксировать оставшиеся follow-up).

---

## Phase 0 — Гейтящий спайк: flask-sock под eventlet (РЕШИТЬ ПЕРВЫМ)

Цель: снять риск, помеченный в roadmap №7 и спеке-центр §7/§10 — работает ли сырой flask-sock-`/ws` под тем же `eventlet`-воркером, что и существующий Flask-SocketIO. От исхода зависит способ деплоя в Phase 1–2 (один воркер eventlet против отдельного процесса/воркера под ws).

### Task 0.1: Спайк-проверка flask-sock + eventlet

**Files:**
- Create (временный, удалить после): `../vsc_web/_spike_sock.py`

- [ ] **Step 1: Установить flask-sock в окружение vsc_web**

Определить интерпретатор vsc_web (свой venv или системный). Проверить:
```bash
cd ../vsc_web && python -c "import flask, eventlet; print(flask.__version__)"
```
Установить flask-sock тем же интерпретатором: `pip install flask-sock`.

- [ ] **Step 2: Написать минимальный спайк**

`_spike_sock.py`: `eventlet.monkey_patch()` первой строкой → создать `Flask` + Flask-SocketIO (`async_mode='eventlet'`) + flask-sock `/echo`-маршрут (`while True: ws.send(ws.receive())`). Запустить через `socketio.run(app, port=5099)` в фоне.

- [ ] **Step 3: Прогнать echo-клиента**

Клиентом `websockets` подключиться к `ws://127.0.0.1:5099/echo`, послать кадр, получить тот же. Параллельно убедиться, что Socket.IO-эндпоинт жив (опц.).

- [ ] **Step 4: Зафиксировать решение**

Записать исход прямо в этот файл плана (раздел «Решение Phase 0» ниже):
- **A. flask-sock работает под eventlet-воркером** → деплой: один `gunicorn -k eventlet -w 1 app:app`, `/ws` и `/p2p` живут в том же процессе (спека-центр §10).
- **B. Не работает / конфликтует** → запустить flask-sock-маршруты на отдельном воркере/процессе (напр. отдельный gunicorn `-k gevent` на свой порт, nginx маршрутизирует `/ws` и `/p2p` туда), реестр in-memory остаётся per-process (для v1 — один воркер, спека-p2p §8). Зафиксировать команду запуска.

- [ ] **Step 5: Удалить спайк, не коммитить мусор**

```bash
rm ../vsc_web/_spike_sock.py
```
Коммитим в `vsc_web` только добавление `flask-sock` в `requirements.txt`:
```bash
cd ../vsc_web && git add requirements.txt && git commit -m "deps: добавить flask-sock для сырых WebSocket-маршрутов"
```

> **Решение Phase 0 (2026-05-31): ВАРИАНТ A.** Сырой `flask-sock==0.7.0` работает под eventlet-воркером в одном процессе с Flask-SocketIO — text и binary echo проходят (flask-sock использует `simple-websocket` с низкоуровневым socket-I/O, совместимым с monkey-patched сокетами eventlet; asyncio не задействован, конфликта циклов нет).
> - **Деплой/локальный запуск для Phase 1–2 и smoke:** один процесс, все маршруты (включая будущие `/ws` и `/p2p`) в нём. Прод: `gunicorn -k eventlet -w 1 app:app` (один воркер — in-memory реестры per-process). Локально/в тестах: запускать **интерпретатором vsc_web** `/home/terrentii/VS_Projects/vsc_web/.venv/bin/python app.py` (поднимает `socketio.run`, порт 5000 по умолчанию). Для тестов на свободном порту — задать порт через env/параметр (см. фикстуру live-сервера в Task 1.7 / 3.3; при необходимости добавить чтение `PORT` в `app.py` точкой входа).
> - **Зависимости vsc_web venv:** `flask-sock==0.7.0` закоммичен в `requirements.txt`. `websockets==16.0` уже установлен в venv (нужен контрактным тестам). `pytest` для тестов vsc_web — **поставить** в venv перед Phase 1 (`/home/terrentii/VS_Projects/vsc_web/.venv/bin/pip install pytest`); не входит в прод-requirements.

---

## Phase 1 — Централизованный сервер в `vsc_web` (TDD)

Все задачи — **в `../vsc_web`**. Эталонный код — спека-центр (`2026-05-30-server-centralized-api.md`); ниже — порядок, точки интеграции и тест-дизайн. Тесты `vsc_web` запускаются интерпретатором vsc_web: `cd ../vsc_web && python -m pytest tests/ -q` (если pytest не стоит — `pip install pytest`).

### Task 1.1: Модель AuthToken + колонка client_msg_id + миграция

**Files:**
- Modify: `../vsc_web/models.py` (добавить класс `AuthToken` по спеке-центр §5; в `Message` — `client_msg_id` + `__table_args__` UNIQUE `(room_id, client_msg_id)` по §6.4)
- Modify: `../vsc_web/app.py` (в блоке `with app.app_context()` рядом со стр.98-108 — idempotent ALTER + CREATE UNIQUE INDEX по §8)

- [ ] **Step 1: Тест — миграция создаёт таблицу/колонку**

`tests/test_centralized_api.py`: фикстура поднимает app с временной SQLite (`:memory:` или tmp-файл), вызывает `db.create_all()` + блок миграции. Тест:
```python
def test_auth_tokens_table_and_client_msg_id_exist(app_ctx):
    from sqlalchemy import inspect as sa_inspect
    from extensions import db
    insp = sa_inspect(db.engine)
    assert 'auth_tokens' in insp.get_table_names()
    cols = {c['name'] for c in insp.get_columns('messages')}
    assert 'client_msg_id' in cols
```

- [ ] **Step 2: Запустить — упадёт** (`auth_tokens` нет / колонки нет). `cd ../vsc_web && python -m pytest tests/test_centralized_api.py::test_auth_tokens_table_and_client_msg_id_exist -q` → FAIL.

- [ ] **Step 3: Реализовать** модель `AuthToken` (§5) и колонку/constraint (§6.4) в `models.py`; миграцию (§8) в `app.py`.

- [ ] **Step 4: Запустить — пройдёт.** Тот же тест → PASS.

- [ ] **Step 5: Commit** (`cd ../vsc_web`): `git add models.py app.py tests/ && git commit -m "feat(central): таблица auth_tokens и колонка client_msg_id"`

### Task 1.2: Bearer-хелперы (`bearer.py`)

**Files:**
- Create: `../vsc_web/bearer.py` (по спеке-центр §5: `issue_token`, `resolve_bearer`, `require_bearer`, плюс `resolve_bearer_token(raw)` для ws — резолв по сырому токену из кадра, не из заголовка)

- [ ] **Step 1: Тест round-trip токена**
```python
def test_issue_and_resolve_token(app_ctx):
    from bearer import issue_token, _hash_token
    from models import AuthToken
    raw = issue_token('alice')
    assert AuthToken.query.filter_by(token_hash=_hash_token(raw)).first().login == 'alice'
```

- [ ] **Step 2: Запустить — FAIL** (нет модуля).

- [ ] **Step 3: Реализовать** `bearer.py` по §5 + добавить `resolve_bearer_token(raw: str) -> str | None` (хэш сырого токена → `AuthToken.login`).

- [ ] **Step 4: PASS.**

- [ ] **Step 5: Commit:** `git add bearer.py tests/ && git commit -m "feat(central): bearer-токены (выпуск/резолв)"`

### Task 1.3: Auth-эндпоинты (`/api/auth/register|login|logout`)

**Files:**
- Create: `../vsc_web/centralized.py` (blueprint `central_bp`; §6.1). Переиспользовать из `auth.py`: `LOGIN_RE` (стр.23), `_ensure_personal_room` (стр.29), `_is_rate_limited`/`_record_attempt`/`_clear_attempts` (стр.57/67/78). НЕ вызывать `login_user`/`session` (§6.1 примечание).

- [ ] **Step 1: Тесты auth** (формы тел — байт-в-байт с `api_client.py:_session_from`, стр.73-88):
```python
def test_register_returns_token_and_user(client):
    r = client.post('/api/auth/register', json={'username': 'alice', 'password': 'pw12'})
    assert r.status_code == 201
    body = r.get_json()
    assert body['user'] == {'id': body['user']['id'], 'username': 'alice'}
    assert isinstance(body['token'], str) and body['token']

def test_register_duplicate_409(client):
    client.post('/api/auth/register', json={'username': 'bob', 'password': 'pw12'})
    r = client.post('/api/auth/register', json={'username': 'bob', 'password': 'pw12'})
    assert r.status_code == 409 and r.get_json() == {'error': 'username_taken'}

def test_login_ok_and_bad_credentials(client):
    client.post('/api/auth/register', json={'username': 'carol', 'password': 'pw12'})
    assert client.post('/api/auth/login', json={'username': 'carol', 'password': 'pw12'}).status_code == 200
    bad = client.post('/api/auth/login', json={'username': 'carol', 'password': 'nope'})
    assert bad.status_code == 401 and bad.get_json() == {'error': 'invalid_credentials'}

def test_logout_invalidates_token(client):
    tok = client.post('/api/auth/register', json={'username': 'dave', 'password': 'pw12'}).get_json()['token']
    h = {'Authorization': f'Bearer {tok}'}
    assert client.post('/api/auth/logout', headers=h).status_code == 204
    assert client.get('/api/rooms', headers=h).status_code == 401
```

- [ ] **Step 2: FAIL** (нет blueprint/маршрутов; `central_bp` ещё не зарегистрирован — см. Task 1.6 для регистрации; для изоляции теста зарегистрировать blueprint во фикстуре app).

- [ ] **Step 3: Реализовать** `/api/auth/register|login|logout` по §6.1 в `centralized.py`.

- [ ] **Step 4: PASS.**

- [ ] **Step 5: Commit:** `git add centralized.py tests/ && git commit -m "feat(central): /api/auth register|login|logout по Bearer"`

### Task 1.4: Комнаты и история (`/api/rooms`, `/api/rooms/<id>/messages`)

**Files:**
- Modify: `../vsc_web/centralized.py` (добавить `GET/POST /api/rooms`, `GET /api/rooms/<int:room_id>/messages`; §6.2, §6.3). Маппинг целое `Room.id` ↔ строковый `room.room_id` — §4 «ключевой момент». Создание комнаты — семантика `rooms.py:create_room` (стр.154-176): 10-значный `room_id`, `is_open=True`, caller — `RoomMember(role='godfather')`.

- [ ] **Step 1: Тесты комнат/истории** (формы — `api_client.py:_room_from`/`_message_from`, курсор `after`/`next_cursor` — §6.3):
```python
def test_create_and_list_rooms(client, auth_header):
    created = client.post('/api/rooms', json={'name': 'проект'}, headers=auth_header).get_json()
    assert set(created) == {'id', 'name', 'is_direct', 'updated_at'} and created['is_direct'] is False
    rooms = client.get('/api/rooms', headers=auth_header).get_json()['rooms']
    assert created['id'] in [r['id'] for r in rooms]

def test_messages_cursor_pagination(client, auth_header):
    rid = client.post('/api/rooms', json={'name': 'r'}, headers=auth_header).get_json()['id']
    for i in range(3):
        client.post('/api/messages', json={'room_id': rid, 'body': f'm{i}',
                                            'client_msg_id': f'c{i}'}, headers=auth_header)
    page = client.get(f'/api/rooms/{rid}/messages?limit=2', headers=auth_header).get_json()
    assert len(page['messages']) == 2 and page['next_cursor'] == page['messages'][-1]['id']
    m = page['messages'][0]
    assert set(m) >= {'id', 'room_id', 'sender', 'body', 'created_at'} and m['room_id'] == rid
    rest = client.get(f"/api/rooms/{rid}/messages?after={page['next_cursor']}", headers=auth_header).get_json()
    assert len(rest['messages']) == 1 and rest['next_cursor'] is None

def test_rooms_requires_bearer(client):
    assert client.get('/api/rooms').status_code == 401
```

- [ ] **Step 2: FAIL.**

- [ ] **Step 3: Реализовать** `/api/rooms` (GET §6.2 / POST §6.2) и `/api/rooms/<int:room_id>/messages` (§6.3). `next_cursor` = id последнего, только если за ним есть ещё записи.

- [ ] **Step 4: PASS.**

- [ ] **Step 5: Commit:** `git add centralized.py tests/ && git commit -m "feat(central): /api/rooms и история по курсору"`

### Task 1.5: Идемпотентная отправка (`POST /api/messages`)

**Files:**
- Modify: `../vsc_web/centralized.py` (`POST /api/messages`; §6.4). Идемпотентность по `(room.room_id, client_msg_id)`.

- [ ] **Step 1: Тест идемпотентности** (`api_client.py:post_message`, стр.158-173 — тело `{room_id, body, client_msg_id}`):
```python
def test_post_message_idempotent(client, auth_header):
    rid = client.post('/api/rooms', json={'name': 'r'}, headers=auth_header).get_json()['id']
    body = {'room_id': rid, 'body': 'hi', 'client_msg_id': 'dup-1'}
    first = client.post('/api/messages', json=body, headers=auth_header).get_json()
    second = client.post('/api/messages', json=body, headers=auth_header).get_json()
    assert first['id'] == second['id']
    assert set(first) >= {'id', 'room_id', 'sender', 'body', 'created_at', 'client_msg_id'}
    page = client.get(f'/api/rooms/{rid}/messages', headers=auth_header).get_json()
    assert len(page['messages']) == 1  # дубля нет
```

- [ ] **Step 2: FAIL.**

- [ ] **Step 3: Реализовать** `POST /api/messages` по §6.4 (резолв room по int id → запись `Message(room_id=room.room_id, author=caller, text=body, client_msg_id=...)`; при повторе вернуть существующую). Фан-аут добавим в Task 1.7.

- [ ] **Step 4: PASS.**

- [ ] **Step 5: Commit:** `git add centralized.py tests/ && git commit -m "feat(central): идемпотентный POST /api/messages"`

### Task 1.6: Регистрация blueprint в app + регрессия веб-версии

**Files:**
- Modify: `../vsc_web/app.py:89-113` (импорт и регистрация `central_bp` с `url_prefix='/api'`; `csrf.exempt(central_bp)`; §9)

- [ ] **Step 1: Тест регрессии** — существующие маршруты живы:
```python
def test_web_routes_still_work(client):
    assert client.get('/').status_code == 200
    assert client.get('/api/rooms/tg').status_code in (200, 401, 403)  # существующий /api жив
```
(Form-вход/Socket.IO `new_message` не ломаем — новые маршруты только добавлены.)

- [ ] **Step 2: FAIL/ERROR** если регистрация ещё не сделана (или blueprint конфликтует).

- [ ] **Step 3: Реализовать** регистрацию по §9 в `app.py`. Проверить отсутствие коллизий путей с существующим `api_bp` (GET `/api/rooms` есть в обоих — в спеке-центр §6.2 это `central_bp`; убедиться, что прежний `api.py:/api/rooms` остаётся отдельным или согласован. **Если коллизия** — оставить новый под Bearer в `central_bp`, прежний `api_bp` не трогать; Flask разрулит по методу/порядку, при пересечении GET — вынести новый список под отдельный путь не нужно, т.к. контракт клиента жёстко ждёт `/api/rooms`; проверить, что Bearer-ветка не перехватывает анонимный веб-GET — клиент шлёт Bearer, веб шлёт cookie). Зафиксировать решение коллизии в комментарии кода.

- [ ] **Step 4: PASS** + весь файл тестов: `python -m pytest tests/test_centralized_api.py -q`.

- [ ] **Step 5: Commit:** `git add app.py tests/ && git commit -m "feat(central): регистрация central_bp, csrf.exempt"`

### Task 1.7: Сырой `/ws` + фан-аут из обоих путей записи

**Files:**
- Create: `../vsc_web/ws_centralized.py` (по §7: реестр `_subs`/`_ws_rooms`, `fanout_message`, `@sock.route('/ws')`)
- Modify: `../vsc_web/app.py` (регистрация `ws_bp` + `sock.init_app(app)`; §9)
- Modify: `../vsc_web/api.py` (`post_message`, после `db.session.commit()` ~стр.43 — вызвать `fanout_message(room.id, {...})` с маппингом §4)
- Modify: `../vsc_web/centralized.py` (`POST /api/messages` — после commit вызвать `fanout_message`)

- [ ] **Step 1: Тест ws-контракта** (кадры — `ws_client.py`: `auth`→`ready`/`error`, push `message`). Поднять реальный сервер в subprocess (см. Phase 0 решение для команды запуска) на свободном порту; клиент — `websockets`:
```python
@pytest.mark.timeout(15)
def test_ws_auth_ready_and_message_fanout(live_server, auth_token, a_room_id):
    import asyncio, json, websockets
    async def run():
        async with websockets.connect(live_server.ws_url + '/ws') as ws:
            await ws.send(json.dumps({'type': 'auth', 'token': auth_token}))
            assert json.loads(await ws.recv())['type'] == 'ready'
            # отправка через REST → push в ws
            live_server.post_message(a_room_id, 'ping', 'cid-1', auth_token)
            frame = json.loads(await asyncio.wait_for(ws.recv(), 5))
            assert frame['type'] == 'message' and frame['room_id'] == a_room_id and frame['body'] == 'ping'
    asyncio.run(run())

@pytest.mark.timeout(15)
def test_ws_unauthorized(live_server):
    import asyncio, json, websockets
    async def run():
        async with websockets.connect(live_server.ws_url + '/ws') as ws:
            await ws.send(json.dumps({'type': 'auth', 'token': 'garbage'}))
            assert json.loads(await ws.recv())['type'] == 'error'
    asyncio.run(run())
```
(Фан-аут из веб-пути проверяется аналогично: вызвать `POST /api/room/<str room_id>/message` и убедиться, что подписчик `/ws` получил `message`.)

- [ ] **Step 2: FAIL** (нет `/ws`).

- [ ] **Step 3: Реализовать** `ws_centralized.py` по §7; зарегистрировать в `app.py` (§9); врезать `fanout_message(room.id, {...})` после commit в обоих путях (`api.py:post_message` и `centralized.py:POST /api/messages`). Маппинг полей строго §4.

- [ ] **Step 4: PASS** — `python -m pytest tests/test_ws_centralized.py -q`. (Требует `pytest-timeout`; при отсутствии — `pip install pytest-timeout` или убрать маркер и обернуть `asyncio.wait_for`.)

- [ ] **Step 5: Commit:** `git add ws_centralized.py app.py api.py centralized.py tests/ && git commit -m "feat(central): сырой /ws и фан-аут из обоих путей записи"`

---

## Phase 2 — Rendezvous + relay `/p2p` в `vsc_web` (TDD)

Все задачи — **в `../vsc_web`**. Эталонный код — спека-p2p §5 (`rendezvous_ws.py`). Семантика идентична `src/mys_decentralized/rendezvous_server.py` (vsc_desktop).

### Task 2.1: Модуль rendezvous_ws + регистрация

**Files:**
- Create: `../vsc_web/rendezvous_ws.py` (по спеке-p2p §5: кодеки `encode_frame`/`frame_type`/`frame_payload`/`parse_hello`/`encode_pair`, реестр `_rooms`, `@sock.route('/p2p')`). Кадры — байт-в-байт с `src/mys_decentralized/protocol.py`.
- Modify: `../vsc_web/app.py` (зарегистрировать bp `/p2p` + `sock.init_app` — если уже инициализирован в Task 1.7, переиспользовать тот же `Sock` либо отдельный, согласно решению Phase 0)

- [ ] **Step 1: Тест pairing** — два клиента с одним `room_id` получают `PAIR` с ролями 0/1 и кандидатами друг друга (спека-p2p §9.2). Кодировать кадры теми же кодеками; поднять live-сервер (Phase 0 команда), клиенты — `websockets` (binary).
```python
@pytest.mark.timeout(15)
def test_pairing_roles_and_candidates(live_server):
    import asyncio, websockets
    from rendezvous_ws import encode_frame, frame_type, frame_payload, parse_hello, HELLO, PAIR
    # helper: hello payload = var-bytes(room_id) | candidates
    async def run():
        rid = b'\x00' * 32
        async def hello(cands):
            ws = await websockets.connect(live_server.ws_url + '/p2p')
            await ws.send(encode_frame(HELLO, _hello_payload(rid, cands)))
            return ws
        a = await hello([('1.1.1.1', 1111)])
        b = await hello([('2.2.2.2', 2222)])
        fa, fb = await asyncio.wait_for(a.recv(), 5), await asyncio.wait_for(b.recv(), 5)
        assert frame_type(fa) == PAIR and frame_type(fb) == PAIR
        ra, ca = _parse_pair(frame_payload(fa)); rb, cb = _parse_pair(frame_payload(fb))
        assert {ra, rb} == {0, 1}
        assert ('2.2.2.2', 2222) in ca and ('1.1.1.1', 1111) in cb
        await a.close(); await b.close()
    asyncio.run(run())
```
(`_hello_payload`/`_parse_pair` — локальные тест-хелперы по wire §3.)

- [ ] **Step 2: FAIL.**

- [ ] **Step 3: Реализовать** `rendezvous_ws.py` по §5; зарегистрировать `/p2p` в `app.py`.

- [ ] **Step 4: PASS.**

- [ ] **Step 5: Commit:** `git add rendezvous_ws.py app.py tests/ && git commit -m "feat(p2p): rendezvous /p2p — pairing по room_id"`

### Task 2.2: Relay (пересылка RELAY как есть) + отказ третьего

**Files:**
- Modify: `../vsc_web/rendezvous_ws.py` (relay-цикл уже в §5-эталоне — покрываем тестами)

- [ ] **Step 1: Тесты relay/лимита** (спека-p2p §9.4, §9.5):
```python
@pytest.mark.timeout(15)
def test_relay_passthrough_and_third_rejected(live_server):
    # A и B спарены; A шлёт RELAY{payload} → B получает те же байты payload.
    # Третий клиент с тем же room_id — соединение закрывается (recv → ConnectionClosed).
    ...
```

- [ ] **Step 2: FAIL/реализовано** (relay уже в §5; тест может сразу пройти — тогда это покрытие, всё равно фиксируем).

- [ ] **Step 3: При необходимости — доработать** (граничные случаи: пир отвалился → RELAY игнор).

- [ ] **Step 4: PASS** — `python -m pytest tests/test_rendezvous_ws.py -q`.

- [ ] **Step 5: Commit:** `git add rendezvous_ws.py tests/ && git commit -m "test(p2p): relay-passthrough и отказ третьего участника"`

---

## Phase 3 — Сквозные e2e со стороны `vsc_desktop`

Все задачи — **в `vsc_desktop`**. Прогон с libsodium на пути (см. шапку).

### Task 3.1: Маркер e2e_server в pytest.ini

**Files:**
- Modify: `vsc_desktop/pytest.ini` (добавить в `markers`: `e2e_server: требует поднятого локального vsc_web`)

- [ ] **Step 1:** Добавить маркер.
- [ ] **Step 2:** `LD_LIBRARY_PATH=<sodium> QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q --markers | grep e2e_server` → присутствует.
- [ ] **Step 3: Commit:** `git add pytest.ini && git commit -m "test: маркер e2e_server"`

### Task 3.2: E2E P2P через встроенный rendezvous_server

**Files:**
- Create: `vsc_desktop/tests/test_e2e_p2p.py` (использует `src/mys_decentralized/rendezvous_server.py` + два `P2PService`/`Session`)

- [ ] **Step 1: Тест happy-path relay** — два клиента, одна фраза → согласованный канал, обмен сообщениями в обе стороны, порядок первого сообщения (prime/очередь). Опереться на существующие интеграционные тесты P2P (найти их: `grep -rl rendezvous_server tests/`) и расширить сценарием полного диалога.
```python
@pytest.mark.asyncio
async def test_p2p_full_dialog_relay(tmp_path):
    # поднять rendezvous_server на свободном порту; два клиента с одной фразой;
    # initiator шлёт prime+msg, responder отвечает; оба видят оба сообщения по порядку.
    ...
```

- [ ] **Step 2: Тест неверной фразы (PAKE-fail)** — разные фразы → `PAKEError`/разрыв с предупреждением.
- [ ] **Step 3: Тест MITM** — подмена `Y`/`CONFIRM` → `PAKEError`.
- [ ] **Step 4: Тест реконнект** — новый транспорт, тот же `room_id` → сессия возобновляется, ratchet продолжается.
- [ ] **Step 5: Запустить весь файл** — все зелёные: `LD_LIBRARY_PATH=<sodium> QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_e2e_p2p.py -q`.
- [ ] **Step 6: Commit:** `git add tests/test_e2e_p2p.py && git commit -m "test(e2e): P2P полный диалог, PAKE-fail, MITM, реконнект"`

### Task 3.3: E2E «Центр» против реального локального vsc_web

**Files:**
- Create: `vsc_desktop/tests/test_e2e_centralized.py` (маркер `e2e_server`; поднимает `../vsc_web` в subprocess на свободном порту с tmp-БД)

- [ ] **Step 1: Фикстура live vsc_web** — subprocess `python app.py`/команда из Phase 0 с `DATABASE_URL=sqlite:///<tmp>` и `PORT`; ждать готовности (poll `GET /`); teardown — терминировать. Пропуск (`pytest.skip`) если интерпретатор/сервер недоступен.

- [ ] **Step 2: Тест полного цикла одного клиента** — `CentralizedService`: register → авто-синк комнат → `create_room`? (создание комнаты из «Центра» — follow-up №6, проверить наличие в клиенте) → `send_message` → история содержит сообщение; повторная отправка с тем же `client_msg_id` идемпотентна.
```python
@pytest.mark.e2e_server
@pytest.mark.asyncio
async def test_central_register_send_sync(live_vsc_web, tmp_path):
    # base_url = live_vsc_web.url; поднять CentralizedService на vault в tmp;
    # register → создать комнату → отправить → получить в истории.
    ...
```

- [ ] **Step 3: Тест real-time доставки между двумя аккаунтами** — два `CentralizedService` (две учётки) в одной комнате; A отправляет → B получает push по `/ws` (live). Если присоединение по `room_id`/инвайт не реализовано в клиенте — задействовать общую комнату через прямую запись `RoomMember` на сервере в фикстуре и задокументировать ограничение.

- [ ] **Step 4: Запустить** (с сервером): `LD_LIBRARY_PATH=<sodium> QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_e2e_centralized.py -q -m e2e_server`. Закрыть любые всплывшие расхождения контракта (правки — в `vsc_web`, отдельными коммитами; имена полей менять нельзя — править сервер под клиента).

- [ ] **Step 5: Commit:** `git add tests/test_e2e_centralized.py && git commit -m "test(e2e): Центр против реального vsc_web — синк, отправка, real-time"`

---

## Phase 4 — Smoke-скрипт для CI

### Task 4.1: scripts/smoke.py

**Files:**
- Create: `vsc_desktop/scripts/smoke.py`
- Create: `vsc_desktop/scripts/README.md`

- [ ] **Step 1:** `smoke.py`: (1) определить `<sodium_dir>` (поиск или env `SODIUM_DIR`), выставить `LD_LIBRARY_PATH`/`QT_QPA_PLATFORM=offscreen`; (2) поднять `../vsc_web` в subprocess (tmp-БД, свободный порт) по команде из Phase 0; (3) запустить `pytest tests/test_e2e_p2p.py tests/test_e2e_centralized.py -m "e2e_server or not e2e_server" -q`; (4) teardown сервера; (5) `sys.exit(pytest_rc)`.

- [ ] **Step 2:** Прогнать `scripts/smoke.py` локально — exit 0, оба набора зелёные.

- [ ] **Step 3:** `scripts/README.md`: как запускать локально (нужен `../vsc_web`, libsodium), переменные `SODIUM_DIR`, и как встроить в CI (отдельный шаг; vsc_web как соседний checkout).

- [ ] **Step 4: Commit:** `git add scripts/smoke.py scripts/README.md && git commit -m "test(e2e): smoke-скрипт для локального и CI прогона"`

### Task 4.2: Отметить №7 в CLAUDE.md

**Files:**
- Modify: `vsc_desktop/CLAUDE.md` (раздел «Продолжение (этапы №7+)»)

- [ ] **Step 1:** Отметить №7 как ✅ с кратким перечнем (серверные контракты в `vsc_web`, e2e оба режима, smoke-скрипт) и зафиксировать оставшиеся follow-up (напр. flask-sock-деплой при нескольких воркерах, присоединение к комнате «Центра» по коду, если не сделано).

- [ ] **Step 2: Commit:** `git add CLAUDE.md && git commit -m "docs: №7 e2e — статус и follow-up"`

---

## Self-Review (закрытие по спеке roadmap §7)

- **E2E «Центр»** против реального `vsc_web`: Phase 1 (сервер) + Task 3.3. ✅ покрыто.
- **E2E P2P** (hole-punch/relay, неверная фраза, MITM, реконнект, порядок первого): Phase 2 (сервер `/p2p`) + Task 3.2 (через встроенный rendezvous). ✅ покрыто. *Примечание:* Task 3.2 гоняет через встроенный `rendezvous_server`; прогон клиента против **серверного** `/p2p` из `vsc_web` — опциональное расширение Task 3.3-стиля (поднять vsc_web, `P2PService(rendezvous_url="ws://127.0.0.1:<port>/p2p")`); добавить как Task 3.2b при необходимости полного доказательства против реального сервера.
- **Серверная закалка `/ws` под боевым стеком** (eventlet/gunicorn): Phase 0 (решение) + деплой-заметки; полная боевая проверка за nginx — вне CI, задокументировать в `scripts/README.md`.
- **Smoke-скрипт для CI:** Phase 4. ✅ покрыто.

**Замечание по scope:** Phase 1 и Phase 2 — независимые серверные подсистемы и шипятся по отдельности; объединены в один план, т.к. цель №7 (доказать работу **целиком**) требует обеих + e2e поверх них, и они делят интеграцию flask-sock/`app.py`/деплой.
