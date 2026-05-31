# Под-проект №6 — Токен + WebSocket API на сервере (vsc_web)

**Статус:** инструкция для агента в `vsc_web` · **Дата:** 2026-05-30

Самодостаточная инструкция (по образцу `2026-05-30-server-rendezvous-relay.md` из
№5). Реализуется **в репозитории `vsc_web`** (Flask + Flask-SQLAlchemy +
Flask-SocketIO, SQLite). Десктоп-клиент (`mys_centralized`) уже написан и
оттестирован против фейкового сервера под **целевой контракт** ниже — сервер
должен реализовать его **байт-в-байт**.

Контракт зафиксирован в `docs/superpowers/specs/2026-05-30-centralized.md` §5–§6;
клиентские кодеки — `src/mys_centralized/api_client.py` и `ws_client.py`. Любое
расхождение имён полей/форм тел ломает синхронизацию.

---

## 1. Цель

Дать десктоп-клиенту вход по **opaque-токену** (`Authorization: Bearer`),
синхронизацию комнат и истории и **real-time** приём новых сообщений по
**сырому WebSocket** `/ws`. Всё — рядом с существующей веб-версией, не ломая её.

## 2. Жёсткие требования (НАРУШАТЬ НЕЛЬЗЯ)

- **Не ломать веб-версию.** Cookie-сессии Flask-Login, CSRFProtect, form-маршруты
  `/register`,`/login`,`/logout`, существующие `/api/*` и Socket.IO (`new_message`)
  продолжают работать без изменений. Новые маршруты — **дополнительно**.
- **Bearer-эндпоинты не используют cookie/CSRF.** Авторизация — только токен;
  blueprint новых JSON-маршрутов освобождается от CSRF (как `csrf.exempt(api_bp)`
  в `app.py`).
- **Сырой WebSocket, не Socket.IO.** Клиент говорит на голом WS (библиотека
  `websockets`), а не по Socket.IO-протоколу. `/ws` — отдельный raw-WS эндпоинт
  (рекомендуется `flask-sock`, как `/p2p` в №5). Существующий Socket.IO для
  веб-UI не трогаем.
- **Токен — секрет.** Хранить только хэш (sha256), как `ApiKey.key_hash`. Логаут
  инвалидирует токен.
- **Время — ISO-8601** строкой (UTC, naive как в моделях: `timestamp.isoformat()`).

## 3. Сверка с текущим кодом (что уже есть)

Проверено по исходникам `vsc_web/` (на 2026-05-30):

- **`models.py`**
  - `User(id:int, login:str unique, password_hash:str, created_at)` — **`login`, не
    `username`**; `get_id()` возвращает `login`.
  - `Room(id:int PK, room_id:str(10) unique, name, is_open, tg_visible,
    created_at, creator_login, personal_login)`. **Два идентификатора:** целочисленный
    `id` и строковый `room_id`. `Message.room_id` (FK) ссылается на **строковый**
    `Room.room_id`.
  - `Message(id:int PK, room_id:str FK, author:str, text:Text, timestamp:DateTime,
    reply_to, media)` — **`author`/`text`/`timestamp`**, не `sender`/`body`/`created_at`.
  - `RoomMember(room_id:str, login:str, role)` — членство.
  - `ApiKey(login, key_hash, label)` — уже есть machine-to-machine ключи
    (`X-Api-Key: vsc_<token>`). Это **долгоживущие** ключи бота, не сессионные токены
    входа — для №6 заводим отдельную таблицу (см. §5), чтобы логаут не бил по ключам.
- **`auth.py`** — form-вход/регистрация, rate-limit по IP
  (`_is_rate_limited`/`_record_attempt`/`_clear_attempts`), `_ensure_personal_room(login)`.
- **`api.py`** (`url_prefix='/api'`, `csrf.exempt(api_bp)`):
  - `GET /api/rooms` → **массив** `[{room_id, name, created_at}]` (открытые,
    непереперсональные, limit 50).
  - `GET /api/room/<room_id>/messages?after=N` → массив
    `[{id, author, text, timestamp, reply_to, media}]`; **`after` — это OFFSET**, не
    курсор по id; limit 200; без `next_cursor`.
  - `POST /api/room/<room_id>/message` `{text, media}` → `{ok, id, author, text, media}`
    201; шлёт Socket.IO `new_message` в комнату; **без идемпотентности**.
  - `GET/POST/DELETE /api/keys` — управление `ApiKey`.
  - Хелперы: `_resolve_api_key()`, `_get_caller()`, `_can_access(room, login)`,
    `_require_csrf_unless_apikey()`.
- **`extensions.py`** — `db`, `login_manager`, `csrf`, `socketio` (Flask-SocketIO).
- **`app.py`** — `eventlet.monkey_patch()` (async_mode `eventlet`), фабрика-модуль
  (глобальный `app`), регистрация blueprints, `csrf.exempt(api_bp)`, idempotent
  ALTER TABLE при старте, `socketio.run(app)`.
- **`requirements.txt`** — Flask 3.1, Flask-Login, Flask-SocketIO 5.5, eventlet,
  **`simple-websocket`** (уже есть — основа `flask-sock`), Werkzeug.

⚠️ Целевой контракт §5–§6 спеки использует **другие имена** (`username`, целочисленный
`room_id`=`Room.id`, `sender/body/created_at`) — все расхождения снимаются маппингом
из §4. **Существующие эндпоинты не меняем**, добавляем новые.

## 4. Таблица соответствия (контракт клиента ↔ модель сервера)

| Поле в контракте (клиент) | Источник в БД | Примечание |
|---|---|---|
| `username` | `User.login` | принимаем `username` в JSON, пишем/ищем `login` |
| `user.id` | `User.id` | целое |
| `token` | новый `AuthToken` (см. §5) | opaque, отдаём сырой один раз |
| room `id` (везде: list, путь, `POST /api/messages.room_id`) | **`Room.id`** (целое) | клиент маршрутизирует по целому id |
| `room.name` | `Room.name` | `null`/строка |
| `room.is_direct` | `Room.personal_login is not None` | личная «Избранное» → `true` |
| `room.updated_at` | макс. `Message.timestamp` в комнате или `Room.created_at` | ISO, опц. |
| message `id` | `Message.id` | курсор пагинации идёт по нему |
| message `room_id` | `Room.id` целое | НЕ строковый `Message.room_id` |
| `sender` | `Message.author` | |
| `body` | `Message.text` | |
| `created_at` | `Message.timestamp.isoformat()` | |
| `client_msg_id` | **новая колонка** `Message.client_msg_id` | идемпотентность |

**Ключевой момент.** Клиент знает комнату как **целое `Room.id`**. Таблица
`Message` связана со **строковым** `Room.room_id`. Поэтому каждый новый эндпоинт:
`Room.query.get(<int id>)` → берём `room.room_id` (строка) для запросов к
`Message`; обратно в ответах/WS `room_id` отдаём как `room.id` (целое).

## 5. Токен-авторизация (новая таблица + Bearer)

Новая модель (в `models.py`):

```python
class AuthToken(db.Model):
    __tablename__ = 'auth_tokens'
    id         = db.Column(db.Integer, primary_key=True)
    login      = db.Column(db.String(64), db.ForeignKey('users.login'),
                           nullable=False, index=True)
    token_hash = db.Column(db.String(64), unique=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=_utcnow, nullable=False)
    last_used  = db.Column(db.DateTime, default=_utcnow, nullable=False)
```

Эталонный хелпер (новый модуль `bearer.py` или в начале нового blueprint):

```python
import hashlib, secrets
from functools import wraps
from flask import request, jsonify, g
from extensions import db
from models import AuthToken, User

def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()

def issue_token(login: str) -> str:
    raw = secrets.token_urlsafe(32)
    db.session.add(AuthToken(login=login, token_hash=_hash_token(raw)))
    db.session.commit()
    return raw  # сырой токен возвращаем ОДИН раз

def resolve_bearer() -> str | None:
    """Login владельца Bearer-токена или None."""
    h = request.headers.get('Authorization', '')
    if not h.startswith('Bearer '):
        return None
    tok = AuthToken.query.filter_by(token_hash=_hash_token(h[7:].strip())).first()
    return tok.login if tok else None

def require_bearer(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        login = resolve_bearer()
        if not login:
            return jsonify({'error': 'unauthorized'}), 401
        g.caller_login = login
        return fn(*a, **kw)
    return wrapper
```

## 6. REST-контракт (точные тела)

Новый blueprint, напр. `centralized.py`, регистрируется с `url_prefix='/api'` и
**`csrf.exempt`**. Тело ошибок единое: `{"error": "<code>"}`. Все ответы — JSON.

### 6.1 Аутентификация

`POST /api/auth/register` — тело `{"username","password"}`, **без** Bearer.
- валидация как в form-`register` (`LOGIN_RE`, длина пароля ≥4, запрет `Anon\d+`);
- занят логин → `409 {"error":"username_taken"}`;
- успех: создать `User`, вызвать `_ensure_personal_room(login)`, выпустить токен →
  `201 {"token": "<raw>", "user": {"id": user.id, "username": user.login}}`.

`POST /api/auth/login` — тело `{"username","password"}`, **без** Bearer.
- rate-limit по IP (переиспользовать `_is_rate_limited`/`_record_attempt`/`_clear_attempts`);
- неверные данные → `401 {"error":"invalid_credentials"}`;
- успех: `_ensure_personal_room(login)`, выпустить токен →
  `200 {"token": "<raw>", "user": {"id": user.id, "username": user.login}}`.

`POST /api/auth/logout` — Bearer. Удалить текущий токен из `auth_tokens` →
`204` (пустое тело). (Клиент игнорирует тело; важен не-ошибочный статус.)

> Регистрация/логин **не трогают cookie-сессию** (не вызывают `login_user`/`session`),
> чтобы не смешивать браузерную сессию с токеном. Только выпуск токена.

### 6.2 Комнаты

`GET /api/rooms` — Bearer. Комнаты, где пользователь — участник (`RoomMember.login`
== caller), включая личную:

```json
{"rooms": [
  {"id": 12, "name": "general", "is_direct": false, "updated_at": "2026-05-30T10:00:00"}
]}
```

- `id` = `Room.id` (целое); `is_direct` = `room.personal_login is not None`;
  `updated_at` = ISO макс. `Message.timestamp` или `room.created_at`.

`POST /api/rooms` — Bearer. Тело `{"name": "..."}` (имя опц., ≤64). Создаёт комнату
по семантике веб-`rooms.create_room`: 10-значный `room_id`, `is_open=True`, caller —
участник с ролью `godfather`. Ответ `201` — одна комната в форме `_room_dict`:

```json
{"id": 13, "name": "проект", "is_direct": false, "updated_at": "2026-05-31T09:00:00"}
```

- Это **другой метод** на `/api/rooms`, коллизии с `GET` (в `api_bp`) нет —
  держим в `central_bp`. Управление комнатой (участники/выход/удаление) из
  десктопа в v1 не предусмотрено.

### 6.3 История

`GET /api/rooms/<int:room_id>/messages?after=<id>&limit=<n>` — Bearer.
- `room_id` в пути — **`Room.id`** (целое). Резолвим: `room = Room.query.get(room_id)`;
  нет/нет доступа → `404`/`403`.
- `after` — **курсор по `Message.id`** (строго `Message.id > after`), не offset.
  Без `after` — с начала. `limit` (дефолт 200, кап 200).
- Запрос к `Message` по **строковому** `room.room_id`, сортировка по `Message.id`.

```json
{"messages": [
  {"id": 101, "room_id": 12, "sender": "alice", "body": "hi",
   "created_at": "2026-05-30T10:00:00"}
],
 "next_cursor": 101}
```

- `next_cursor` = `id` последнего элемента страницы, **если** есть ещё записи за ним;
  иначе `null`.

### 6.4 Отправка (идемпотентная)

`POST /api/messages` — Bearer. Тело `{"room_id": <int Room.id>, "body": "...",
"client_msg_id": "<uuid hex>"}`.
- резолвим `room = Room.query.get(room_id)`; нет/нет доступа → `404`/`403`;
- **идемпотентность:** если существует `Message` с тем же `(room.room_id,
  client_msg_id)` — вернуть **ту же** запись (не создавать дубль);
- иначе создать `Message(room_id=room.room_id, author=caller, text=body,
  timestamp=utcnow, client_msg_id=client_msg_id)`, **фан-аут в `/ws` и Socket.IO**
  (см. §7);
- ответ `200`:

```json
{"id": 102, "room_id": 12, "sender": "alice", "body": "...",
 "created_at": "2026-05-30T10:01:00", "client_msg_id": "<uuid>"}
```

Колонка идемпотентности (в `models.py`, + миграция §8):

```python
client_msg_id = db.Column(db.String(64), nullable=True)
__table_args__ = (db.UniqueConstraint('room_id', 'client_msg_id',
                                       name='uq_msg_client_id'),)
```

(NULL допускается множественно — старые/веб-сообщения без `client_msg_id` не
конфликтуют.)

## 7. WebSocket `/ws` (сырой, flask-sock)

Клиентские кадры — JSON-объекты (`src/mys_centralized/ws_client.py`):

1. Клиент → сервер первым кадром: `{"type":"auth","token":"<raw token>"}`.
2. Сервер → `{"type":"ready"}` (успех) **или** `{"type":"error","code":"unauthorized"}`
   и закрыть соединение.
3. После `ready` сервер пушит по всем комнатам пользователя при появлении нового
   сообщения (в т.ч. созданного веб-версией через Socket.IO-путь):
   `{"type":"message","room_id":<int Room.id>,"id":<Message.id>,"sender":<author>,
   "body":<text>,"created_at":<iso>}`.
4. Keepalive — штатный WS ping/pong (клиент шлёт ping; `flask-sock`/`simple-websocket`
   отвечают автоматически).

Эталонный модуль `ws_centralized.py` (in-process реестр подписчиков; фан-аут
потокобезопасный — под eventlet это greenlet'ы):

```python
import json, threading
from flask import Blueprint
from flask_sock import Sock
from bearer import resolve_bearer_token  # вариант resolve_bearer по сырому токену
from models import Room, RoomMember

sock = Sock()  # init_app в app.py
ws_bp = Blueprint('ws_centralized', __name__)

_subs: dict[int, set] = {}      # Room.id -> set(ws)
_ws_rooms: dict[object, set] = {}  # ws -> set(Room.id)
_lock = threading.Lock()

def _rooms_for(login: str) -> list[int]:
    rids = [m.room_id for m in RoomMember.query.filter_by(login=login).all()]
    return [r.id for r in Room.query.filter(Room.room_id.in_(rids)).all()] if rids else []

def fanout_message(room_db_id: int, payload: dict) -> None:
    """Вызывать ПОСЛЕ commit из обоих путей записи (REST §6.4 и веб post_message)."""
    frame = json.dumps({"type": "message", **payload})
    with _lock:
        targets = list(_subs.get(room_db_id, ()))
    for ws in targets:
        try:
            ws.send(frame)
        except Exception:
            pass

@sock.route('/ws', bp=ws_bp)
def ws_centralized(ws):
    raw = ws.receive()  # первый кадр — auth
    try:
        msg = json.loads(raw)
    except Exception:
        ws.send(json.dumps({"type": "error", "code": "bad_request"})); return
    login = resolve_bearer_token(msg.get("token", "")) if msg.get("type") == "auth" else None
    if not login:
        ws.send(json.dumps({"type": "error", "code": "unauthorized"})); return
    ws.send(json.dumps({"type": "ready"}))
    room_ids = _rooms_for(login)
    with _lock:
        _ws_rooms[ws] = set(room_ids)
        for rid in room_ids:
            _subs.setdefault(rid, set()).add(ws)
    try:
        while True:
            if ws.receive() is None:   # клиент закрыл
                break
    finally:
        with _lock:
            for rid in _ws_rooms.pop(ws, ()):
                _subs.get(rid, set()).discard(ws)
```

`resolve_bearer_token(raw)` — как `resolve_bearer()`, но по сырому токену из кадра
(не из заголовка): хэш → `AuthToken`.

**Фан-аут из обоих путей записи.** И в новом `POST /api/messages` (§6.4), и в
существующем веб-`POST /api/room/<room_id>/message` после `db.session.commit()`
вызвать `fanout_message(room.id, {...})` с маппингом полей (§4). Так десктоп видит
и сообщения, отправленные из браузера. (Существующий `socketio.emit('new_message',…)`
оставляем для веб-UI.)

> Под eventlet `flask-sock` работает с воркером `eventlet`; реестр и `fanout`
> исполняются в greenlet'ах одного процесса — `threading.Lock` достаточно. При
> нескольких воркерах нужен общий брокер (см. §10, follow-up — не для v1).

## 8. Миграция схемы

По образцу idempotent-ALTER в `app.py` (в `with app.app_context()` после
`db.create_all()` / при старте):

```python
from sqlalchemy import text, inspect as sa_inspect
insp = sa_inspect(db.engine)
cols = {c['name'] for c in insp.get_columns('messages')}
if 'client_msg_id' not in cols:
    with db.engine.connect() as c:
        c.execute(text('ALTER TABLE messages ADD COLUMN client_msg_id VARCHAR(64)'))
        c.commit()
# auth_tokens создаётся через db.create_all() (новая модель).
```

UNIQUE `(room_id, client_msg_id)` для существующей БД добавить отдельным
`CREATE UNIQUE INDEX IF NOT EXISTS` (SQLite не добавляет constraint через ALTER):

```python
c.execute(text('CREATE UNIQUE INDEX IF NOT EXISTS uq_msg_client_id '
               'ON messages(room_id, client_msg_id)'))
```

## 9. Регистрация в приложении (`app.py`)

```python
from extensions import db, login_manager, csrf, socketio
from centralized import central_bp        # новый REST blueprint (§6)
from ws_centralized import sock, ws_bp, fanout_message

app.register_blueprint(central_bp, url_prefix='/api')
csrf.exempt(central_bp)                    # Bearer, без CSRF
app.register_blueprint(ws_bp)
sock.init_app(app)                         # flask-sock
```

Добавить в `requirements.txt`: `flask-sock` (на базе уже присутствующего
`simple-websocket`).

## 10. Деплой за nginx

Как `/p2p` в №5 — проксировать `/ws` с Upgrade-заголовками:

```nginx
location /ws {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_read_timeout 3600s;
}
```

Gunicorn — воркер `eventlet` (как для Socket.IO):
`gunicorn -k eventlet -w 1 app:app` (один воркер для in-process реестра §7).

## 11. Тесты контракта (на стороне vsc_web)

- **auth:** register (новый/занятый `409`), login (успех/`401`/rate-limit),
  logout инвалидирует токен (повтор с тем же Bearer → `401`).
- **rooms:** `GET /api/rooms` под Bearer возвращает комнаты участника в форме
  `{"rooms":[{id,name,is_direct,updated_at}]}`; без токена → `401`.
- **messages:** пагинация по `after`(id)/`limit`/`next_cursor`; поля
  `id,room_id,sender,body,created_at`; `room_id` = `Room.id` (целое).
- **идемпотентность:** двойной `POST /api/messages` с одним `client_msg_id` →
  один `Message`, один и тот же `id` в ответе.
- **WS:** auth (ready / unauthorized), приём `message` после `POST /api/messages`,
  приём `message` после **веб**-`POST /api/room/<rid>/message` (фан-аут из обоих
  путей), закрытие чистит реестр.
- **регрессия веб-версии:** form-вход, существующие `/api/*`, Socket.IO
  `new_message` работают как прежде.

Тела сверять с клиентом байт-в-байт: `src/mys_centralized/api_client.py`
(`_session_from`, `_message_from`, формы запросов) и `ws_client.py` (кадры
`auth`/`ready`/`error`/`message`).

## 12. Follow-up (НЕ для v1)

- Несколько воркеров/инстансов → общий pub/sub для `/ws` (Redis/брокер).
- TTL/ротация токенов, список активных сессий, отзыв.
- Создание/управление комнатами и приглашения из десктопа (сейчас комнаты
  заводятся в веб-версии; десктоп лишь синхронит свои).
- `updated_at` как индексируемая колонка (сейчас — производная).

## 13. Критерий готовности

- Bearer-вход (`/api/auth/register|login|logout`) с токен-таблицей; логаут
  инвалидирует токен.
- `GET /api/rooms`, `GET /api/rooms/<id>/messages` (курсор `after`/`limit`/
  `next_cursor`), `POST /api/messages` (идемпотентный) — в формах §6, имена/типы
  по таблице §4.
- Сырой WS `/ws`: `auth`→`ready`, пуш `message` подписчикам комнаты из **обоих**
  путей записи.
- Веб-версия (cookie/CSRF/Socket.IO/form-маршруты/существующие `/api/*`) не
  сломана; новые маршруты освобождены от CSRF и используют только Bearer.
- Тесты §11 зелёные.
