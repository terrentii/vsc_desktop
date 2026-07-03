# Под-проект №5 — Rendezvous + Relay на сервере (vsc_web)

> **Это инструкция для агента, работающего в репозитории `vsc_web`** (Flask +
> SQLAlchemy + SQLite, https://github.com/terrentii/vsc_web). Она самодостаточна:
> описывает ЧТО реализовать и ПОЧЕМУ; куда именно класть файлы — решай по
> структуре репозитория. Эталонная реализация на чистом asyncio уже есть в
> клиентском репозитории `vsc_desktop`: `src/mys_decentralized/rendezvous_server.py`
> (можно использовать как образец семантики — её и переносим, меняя только
> транспортный слой на flask-sock).

## 1. Цель

Добавить в веб-сервер **WebSocket-эндпоинт rendezvous + relay** для
децентрализованного режима мессенджера. Два анонимных клиента, знающие общую
секретную фразу, выводят из неё одинаковый непрозрачный `room_id` (32 байта) и
находят друг друга на сервере по этому `room_id`. Дальше сервер **ретранслирует
непрозрачные E2E-кадры** между ними (relay-путь) и сообщает адреса-кандидаты для
попытки прямого соединения (hole-punch).

Транспорт — WebSocket поверх того же порта/домена, что и веб-версия (один порт,
WSS, дружит с прокси и фаерволами). Клиент уже переведён на WS и подключается к
URL вида `wss://soufos.ru/p2p`.

## 2. Жёсткие требования безопасности (НАРУШАТЬ НЕЛЬЗЯ)

- Сервер **не видит** секретную фразу и **не видит** открытый текст сообщений.
  Он оперирует только `room_id` и **непрозрачными** байтами `RELAY`-payload.
- Сервер **не парсит и не логирует** payload `RELAY`. Пересылает байты как есть.
- **Никакой персистентности.** Rendezvous полностью in-memory и эфемерный: ни
  `room_id`, ни кадры, ни кандидаты НЕ пишутся в SQLite/лог/диск. В v1 нет
  store-and-forward (оффлайн-доставки). Комната живёт только пока оба онлайн.
- Аутентификация для rendezvous **не нужна** (анонимность). Минимальная защита от
  абьюза: комната максимум на 2 участника; опционально — лимит соединений с IP и
  таймаут «осиротевшей» комнаты (один зашёл, второй не пришёл за N минут — закрыть).
- Только бинарные WebSocket-сообщения. Текстовые игнорировать/закрывать.

## 3. Wire-протокол (точные байты)

Один кадр = одно бинарное WS-сообщение. Все целые — big-endian.

```
Кадр:        u8 type | u8 flags | u32 length | payload[length]
var-bytes:   u16 len | bytes
candidates:  u8 count | count×( var-bytes(host_utf8) | u16 port )
```

Типы (`type`):

| Имя        | Код | Кто шлёт            | Сервер обрабатывает? |
|------------|-----|---------------------|----------------------|
| HELLO      | 1   | клиент → сервер     | да (парсит)          |
| PAIR       | 2   | сервер → клиент     | да (формирует)       |
| PUNCH      | 3   | клиент ↔ клиент     | нет (внутри relay/прямого) |
| PUNCH_ACK  | 4   | клиент ↔ клиент     | нет                  |
| RELAY      | 5   | клиент ↔ сервер ↔ клиент | да (пересылает as-is) |
| PAKE       | 6   | внутри RELAY        | нет (непрозрачно)    |
| CONFIRM    | 7   | внутри RELAY        | нет (непрозрачно)    |
| DATA       | 8   | внутри RELAY        | нет (непрозрачно)    |

Сервер реагирует только на **HELLO** и **RELAY** и формирует **PAIR**. Всё
остальное (PAKE/CONFIRM/DATA/PUNCH) едет **внутри** payload `RELAY` и для сервера
непрозрачно.

Payload-структуры:

- `HELLO`  payload = `var-bytes(room_id) | candidates(свои)`
- `PAIR`   payload = `u8 role | candidates(пира)`, где `role`: `0 = INITIATOR`,
  `1 = RESPONDER`.
- `RELAY`  payload = непрозрачные байты (внутренний кадр пира). Пересылать **весь
  принятый кадр RELAY целиком**, не трогая payload.

`flags` сейчас всегда 0 — читать, но не интерпретировать.

## 4. Поведение сервера (семантика)

Состояние: `rooms: dict[room_id_bytes -> list[Member]]`, где `Member` хранит
ws-соединение, назначенную роль и кандидаты. Доступ к `rooms` — под общим
замком (см. §5 про конкуррентность).

На одно WS-соединение:

1. Принять **первое** бинарное сообщение. Оно обязано быть `HELLO`. Иначе —
   закрыть соединение. Распарсить `room_id` и кандидаты.
2. Взять/создать комнату по `room_id`.
   - Если в комнате уже 2 участника — отклонить (закрыть соединение): v1 только 1:1.
   - Иначе назначить роль по порядку входа: первый — `INITIATOR (0)`, второй —
     `RESPONDER (1)`. Добавить `Member` в комнату.
3. Если после добавления в комнате стало **2** участника — разослать `PAIR` обоим:
   - первому: `PAIR(role=первого, candidates=кандидаты второго)`;
   - второму: `PAIR(role=второго, candidates=кандидаты первого)`.
4. Войти в цикл приёма сообщений этого соединения. На каждое сообщение:
   - распарсить тип кадра (только заголовок — 6 байт);
   - если `RELAY` — найти **другого** участника той же комнаты и переслать ему
     **весь принятый кадр без изменений**. Если пира нет (ещё/уже не в комнате) —
     просто игнорировать;
   - прочие типы игнорировать.
5. При закрытии/обрыве соединения — удалить `Member` из комнаты; если комната
   опустела — удалить её из `rooms`. Обрыв одного участника не должен ронять
   обработчик другого (другой узнает об обрыве по ошибке отправки/закрытию).

Это ровно семантика эталонного `rendezvous_server.py` из `vsc_desktop` (там тот
же протокол на asyncio).

## 5. Реализация на Flask (рекомендация: flask-sock)

Flask — WSGI (синхронный). Для **сырых бинарных** WebSocket-кадров проще всего
**flask-sock** (тонкая обёртка над WebSocket, без своего протокола поверх — в
отличие от Flask-SocketIO, который НЕ подходит: он навязывает свой фрейминг).

- `pip install flask-sock` (+ для прода gunicorn с gevent-воркером, см. §7).
- Каждый ws-обработчик flask-sock — **блокирующий цикл** в своём
  greenlet/потоке: `while True: msg = ws.receive()`. `ws.receive()` для бинарного
  кадра вернёт `bytes`, `ws.send(bytes)` отправит бинарный кадр.
- Реестр комнат — общий `dict` под `threading.Lock` (при gevent-воркере с
  `monkey.patch_all()` стандартный `Lock` становится gevent-совместимым).
- Отправку в ws пира защитить **per-member замком** (в один ws могут одновременно
  писать: код пейринга и relay-цикл соседа). `receive()` вызывает только владелец.

### Эталонный модуль (портировать в структуру vsc_web)

```python
# rendezvous_ws.py — WebSocket rendezvous + relay для децентрализованного режима.
# Никакой персистентности: всё in-memory и эфемерно. Сервер не парсит payload RELAY.

import threading
from dataclasses import dataclass, field

from flask import Blueprint
from flask_sock import Sock

# --- кодеки кадров/полей (точное соответствие клиенту) ----------------------

HELLO, PAIR, RELAY = 1, 2, 5
ROLE_INITIATOR, ROLE_RESPONDER = 0, 1
_HEADER = 6


def encode_frame(mtype: int, payload: bytes, flags: int = 0) -> bytes:
    return bytes([mtype, flags & 0xFF]) + len(payload).to_bytes(4, "big") + payload


def frame_type(buf: bytes) -> int:
    if len(buf) < _HEADER:
        raise ValueError("усечённый заголовок кадра")
    length = int.from_bytes(buf[2:6], "big")
    if len(buf) < _HEADER + length:
        raise ValueError("неполный payload кадра")
    return buf[0]


def frame_payload(buf: bytes) -> bytes:
    length = int.from_bytes(buf[2:6], "big")
    return buf[_HEADER:_HEADER + length]


def _get_var(mv: memoryview, pos: int):
    n = int.from_bytes(mv[pos:pos + 2], "big")
    pos += 2
    return bytes(mv[pos:pos + n]), pos + n


def _put_var(buf: bytearray, chunk: bytes):
    buf += len(chunk).to_bytes(2, "big") + chunk


def parse_hello(payload: bytes):
    """HELLO payload -> (room_id, candidates)."""
    mv = memoryview(payload)
    room_id, pos = _get_var(mv, 0)
    count = mv[pos]; pos += 1
    candidates = []
    for _ in range(count):
        host, pos = _get_var(mv, pos)
        port = int.from_bytes(mv[pos:pos + 2], "big"); pos += 2
        candidates.append((host.decode("utf-8"), port))
    return room_id, candidates


def encode_pair(role: int, peer_candidates) -> bytes:
    buf = bytearray([role, len(peer_candidates)])
    for host, port in peer_candidates:
        _put_var(buf, host.encode("utf-8"))
        buf += port.to_bytes(2, "big")
    return encode_frame(PAIR, bytes(buf))


# --- реестр комнат -----------------------------------------------------------

@dataclass
class _Member:
    ws: object
    role: int
    candidates: list
    send_lock: threading.Lock = field(default_factory=threading.Lock)

    def send(self, data: bytes):
        with self.send_lock:
            self.ws.send(data)


_rooms: dict[bytes, list] = {}
_rooms_lock = threading.Lock()


def _peer_of(room_id: bytes, member: _Member):
    for other in _rooms.get(room_id, ()):
        if other is not member:
            return other
    return None


# --- Blueprint + ws-маршрут --------------------------------------------------

bp = Blueprint("p2p", __name__)
sock = Sock()  # инициализировать на app: sock.init_app(app)


@sock.route("/p2p", bp=bp)            # подгони путь под маршрутизацию vsc_web
def p2p(ws):
    room_id = None
    member = None
    try:
        hello = ws.receive()          # первое сообщение
        if not isinstance(hello, (bytes, bytearray)) or frame_type(hello) != HELLO:
            return
        room_id, candidates = parse_hello(frame_payload(hello))

        with _rooms_lock:
            room = _rooms.setdefault(room_id, [])
            if len(room) >= 2:
                return                # комната занята (1:1)
            role = ROLE_INITIATOR if not room else ROLE_RESPONDER
            member = _Member(ws, role, candidates)
            room.append(member)
            pair_now = len(room) == 2
            first, second = (room[0], room[1]) if pair_now else (None, None)

        if pair_now:
            first.send(encode_pair(first.role, second.candidates))
            second.send(encode_pair(second.role, first.candidates))

        while True:
            msg = ws.receive()
            if msg is None:           # соединение закрыто
                break
            if not isinstance(msg, (bytes, bytearray)):
                continue
            if frame_type(msg) == RELAY:
                with _rooms_lock:
                    peer = _peer_of(room_id, member)
                if peer is not None:
                    try:
                        peer.send(bytes(msg))   # пересылаем кадр как есть
                    except Exception:
                        pass          # пир отвалился — relay-цикл соседа это заметит
    except Exception:
        pass
    finally:
        if room_id is not None and member is not None:
            with _rooms_lock:
                room = _rooms.get(room_id)
                if room is not None and member in room:
                    room.remove(member)
                    if not room:
                        _rooms.pop(room_id, None)
```

Подключение к приложению (адаптируй под фабрику `create_app`/структуру vsc_web):

```python
# где создаётся app:
from .rendezvous_ws import sock, bp
app.register_blueprint(bp)
sock.init_app(app)
```

> Заметка по `@sock.route(..., bp=bp)`: если в вашей версии flask-sock нет
> параметра `bp=`, повесь маршрут прямо на `sock` после `sock.init_app(app)` или
> используй паттерн из доков flask-sock вашей версии. Главное — путь `/p2p`
> (или согласованный с клиентом) и бинарный ws-хэндлер с логикой выше.

## 6. Конфигурация URL

Клиент (`vsc_desktop`) подключается к `rendezvous_url` (его принимает
`P2PService(vault, rendezvous_url, ...)`). Согласуй путь:

- прод: `wss://soufos.ru/p2p`
- локально: `ws://127.0.0.1:5000/p2p`

Этот URL должен попасть в настройки десктоп-клиента (отдельная задача в
`vsc_desktop`: вынести его в конфиг/экран настроек).

## 7. Деплой

flask-sock требует WSGI-сервер с поддержкой WebSocket-апгрейда:

- **gunicorn + gevent**: `gunicorn -k gevent -w 1 'app:app'` (для нескольких
  воркеров реестр комнат должен быть общим — см. §8 про масштабирование; на старте
  достаточно `-w 1`). В точке входа сделать `from gevent import monkey;
  monkey.patch_all()` **до** импорта приложения.
- **dev-сервер** Werkzeug (`flask run`) поддерживает flask-sock для разработки.
- За nginx — пробросить апгрейд для `/p2p`:

```nginx
location /p2p {
    proxy_pass http://127.0.0.1:5000/p2p;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_read_timeout 3600s;   # долгоживущее соединение
}
```

TLS (WSS) терминируется на nginx — отдельный сертификат не нужен, работает поверх
существующего HTTPS-домена.

## 8. Масштабирование (на будущее, НЕ для v1)

Реестр комнат in-memory привязан к процессу. При нескольких воркерах/инстансах два
клиента одной комнаты могут попасть в разные процессы и не спарятся. Варианты на
потом: один воркер для `/p2p`; sticky-routing по `room_id`; или общий брокер
(Redis pub/sub) для пересылки `RELAY` между процессами. Для v1 — **один воркер**.

## 9. Тестирование на стороне vsc_web

Минимальный pytest (клиент — библиотека `websockets`), без знания крипто:

1. Поднять приложение с ws-маршрутом (тестовый сервер).
2. Два клиента шлют `HELLO` с одним `room_id` → оба получают `PAIR` с корректными
   ролями (0 и 1) и кандидатами друг друга.
3. Разные `room_id` → не парятся (второй клиент ждёт и не получает `PAIR`).
4. Relay: клиент A шлёт `RELAY{payload}` → клиент B получает **те же байты**
   payload (сервер не изменил/не прочитал содержимое).
5. Комната на 3-го клиента — отклонение.

Кадры для тестов кодируй теми же кодеками (§3/§5). Можно свериться с эталоном:
прогнать против `rendezvous_server.py` из `vsc_desktop` и убедиться, что клиентский
`RendezvousClient`/`RelayTransport` работает и с вашим сервером идентично.

## 10. Критерий готовности

- WS-эндпоинт `/p2p` парит клиентов по `room_id`, шлёт `PAIR` с ролями и
  кандидатами, ретранслирует `RELAY` без чтения payload.
- Нет персистентности rendezvous; payload не логируется.
- Десктоп-клиент `vsc_desktop` (через `P2PService(..., rendezvous_url="wss://.../p2p")`)
  успешно проходит хендшейк и обмен сообщениями обоими путями (relay и, если сеть
  позволяет, direct). Семантика кадров идентична эталону.

## 11. Аддендум — `PEER_LEFT` (онлайн-статус, реконнект)

Добавлено после закрытия основной части спеки, для UI-индикатора «собеседник
онлайн/офлайн» в десктопе. **Уже реализовано и протестировано** в `vsc_web` —
описано здесь для справки и на случай пересоздания сервера с нуля.

Проблема: закрытие WS одного пира само по себе не обрывает WS второго (сервер
просто перестаёт форвардить `RELAY` дальше, но собственное соединение второго
пира с сервером остаётся живым) — без явного сигнала клиент никогда не узнает,
что собеседник ушёл.

Решение: новый тип кадра `PEER_LEFT = 9` (пустой payload, как `PUNCH`). Когда
участник покидает комнату (соединение закрылось/оборвалось), сервер шлёт
`PEER_LEFT` **оставшемуся** участнику той же комнаты — тем же кодом
`encode_frame`, что и остальные кадры. Ничего нового не парсится и не хранится:
членство в комнате сервер и так знает.

Референс — `rendezvous_server.py` (`vsc_desktop`) и уже применённый патч
`vsc_web/rendezvous_ws.py`: в `finally`-блоке обработчика `/p2p`, после удаления
ушедшего участника из комнаты, разослать `PEER_LEFT` всем, кто остался в списке
(снимок под локом, отправка — вне лока, чтобы не блокировать другие комнаты).

Клиентская сторона (`vsc_desktop`) уже готова: `RelayTransport.recv()`
превращает входящий `PEER_LEFT` в `TransportError` — для вызывающего кода это
неотличимо от настоящего обрыва соединения.

Тест на стороне vsc_web (уже есть, `tests/test_rendezvous_ws.py`): два клиента
парятся, первый закрывает соединение, второй должен получить кадр типа
`PEER_LEFT` (а не тишину/таймаут).
