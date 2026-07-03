"""Оркестратор P2P: asyncio в фоновом потоке + потокобезопасный мост для UI.

Связывает rendezvous → транспорт → хендшейк → сессию и хранит активные сессии
по ``conversation_id``. Публичные методы (``start_session``/``send``/``stop``)
вызываются из главного потока и планируют корутины в свой event loop через
``run_coroutine_threadsafe``. Колбэки (``on_message``/``on_state_change``/
``on_error``) вызываются из потока сервиса; маршалинг в Qt-сигналы — задача
вышестоящего UI-слоя (в этом модуле Qt нет — граница CLAUDE.md).
"""

import asyncio
import threading
from collections.abc import Callable

from .handshake import handshake
from .protocol import Role, derive_room_params
from .rendezvous import RendezvousClient
from .session import Session, open_session
from .transport import (
    RelayTransport,
    establish_transport,
    open_udp_endpoint,
)

OnMessage = Callable[[int, bytes], None]
OnStateChange = Callable[[int, str], None]
OnError = Callable[[int | None, Exception], None]


def _noop(*_args):
    pass


async def _safe_close(obj) -> None:
    """Закрыть транспорт/rendezvous, проглатывая ошибки (путь очистки)."""
    if obj is None:
        return
    try:
        await obj.close()
    except Exception:
        pass


class P2PService:
    def __init__(
        self,
        vault,
        rendezvous_url: str,
        *,
        mode: str = "decentralized",
        on_message: OnMessage | None = None,
        on_state_change: OnStateChange | None = None,
        on_error: OnError | None = None,
        connect_timeout: float = 300.0,
        punch_timeout: float = 1.0,
        allow_direct: bool = True,
    ):
        self._vault = vault
        self._rendezvous_url = rendezvous_url
        self._mode = mode
        self._on_message = on_message or _noop
        self._on_state_change = on_state_change or _noop
        self._on_error = on_error or _noop
        self._connect_timeout = connect_timeout
        self._punch_timeout = punch_timeout
        self._allow_direct = allow_direct

        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._sessions: dict[int, Session] = {}
        self._roles: dict[int, Role] = {}

    # --- жизненный цикл потока/loop -------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run_loop, name="mys-p2p", daemon=True
        )
        self._thread.start()
        self._ready.wait()

    def _run_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        try:
            self._loop.run_forever()
        finally:
            self._loop.close()

    def _submit(self, coro, timeout: float | None = None):
        if self._loop is None:
            raise RuntimeError("сервис не запущен")
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return fut.result(timeout)

    def stop(self) -> None:
        if self._loop is None:
            return
        try:
            self._submit(self._shutdown(), timeout=10.0)
        except Exception:
            pass
        self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        self._thread = None
        self._loop = None
        self._ready.clear()

    async def _shutdown(self) -> None:
        for session in list(self._sessions.values()):
            await session.close()
        self._sessions.clear()
        self._roles.clear()

    # --- потокобезопасный API -------------------------------------------------

    def has_session(self, conversation_id: int) -> bool:
        return conversation_id in self._sessions

    def role_of(self, conversation_id: int) -> Role | None:
        """Роль в беседе (INITIATOR/RESPONDER) — назначена rendezvous-сервером.

        В Double Ratchet первым отправляет INITIATOR; RESPONDER может слать только
        после первого принятого сообщения (см. follow-up в спецификации №4)."""
        return self._roles.get(conversation_id)

    def start_session(self, phrase: str, *, timeout: float | None = None) -> int:
        """Поднять P2P-сессию из фразы; вернуть ``conversation_id``.

        Блокирует до установления канала и хендшейка (по умолчанию до
        ``connect_timeout`` — 5 минут — пока пир не войдёт в комнату). Провал
        PAKE/таймаут пира пробрасывается вызывающему (PAKEError/PeerUnavailable)
        для показа в UI. ``timeout`` переопределяет ожидание пира на этот вызов.
        """
        budget = (timeout or self._connect_timeout) + 10.0
        return self._submit(self._start_session(phrase, timeout), timeout=budget)

    def resolve_conversation(self, phrase: str) -> int:
        """Найти/завести беседу по фразе локально, без сети.

        Только vault-операции (потокобезопасны сами по себе — не требуют event
        loop сервиса) — можно звать из любого потока ДО ``start_session``, чтобы
        сразу получить ``conversation_id`` и показать в UI окно ожидания пира,
        не дожидаясь сетевого хендшейка."""
        room_id, _prs = derive_room_params(phrase)
        return self._conversation_for(room_id)

    def reconnect(self, conversation_id: int, *, timeout: float | None = None) -> None:
        """Возобновить P2P-канал уже известной беседы без повторного ввода фразы.

        Требует, чтобы ``prs`` для этой беседы уже был сохранён (см.
        ``start_session`` — сохраняет его при первом подключении); иначе —
        ``RuntimeError`` с понятным текстом для UI. Блокирует так же, как
        ``start_session`` (по умолчанию до 5 минут ожидания пира)."""
        budget = (timeout or self._connect_timeout) + 10.0
        self._submit(self._reconnect(conversation_id, timeout), timeout=budget)

    def send(self, conversation_id: int, text: str, *, timeout: float = 15.0) -> None:
        self._submit(self._send(conversation_id, text), timeout=timeout)

    def send_file(
        self, conversation_id: int, filename: str, mime_type: str, data: bytes,
        *, timeout: float = 60.0,
    ) -> None:
        """Отправить файл через активную сессию беседы (блокирует до отправки всех
        чанков). Таймаут выше, чем у ``send`` — до полусотни чанков на 50 МБ."""
        self._submit(
            self._send_file(conversation_id, filename, mime_type, data), timeout=timeout
        )

    def stop_session(self, conversation_id: int, *, timeout: float = 10.0) -> None:
        self._submit(self._stop_session(conversation_id), timeout=timeout)

    # --- корутины (исполняются в loop-потоке) ---------------------------------

    def _conversation_for(self, room_id: bytes) -> int:
        for conv in self._vault.conversations.list(self._mode):
            if conv["room_id"] == room_id:
                return conv["id"]
        return self._vault.conversations.add(mode=self._mode, room_id=room_id)

    async def _start_session(self, phrase: str, timeout: float | None = None) -> int:
        room_id, prs = derive_room_params(phrase)
        conv_id = self._conversation_for(room_id)
        # Сохраняем PRS сразу — даже если сам коннект ниже провалится/истечёт по
        # таймауту, беседа уже реконнектится дальше без повторного ввода фразы.
        self._vault.conversations.set_prs(conv_id, prs)
        await self._connect(conv_id, room_id, prs, timeout=timeout)
        return conv_id

    async def _reconnect(self, conversation_id: int, timeout: float | None = None) -> None:
        row = self._vault.conversations.get(conversation_id)
        if row is None:
            raise RuntimeError(f"беседа {conversation_id} не найдена")
        room_id, prs = row.get("room_id"), row.get("p2p_prs")
        if room_id is None or prs is None:
            raise RuntimeError(
                "для этого канала нет сохранённой фразы — откройте его заново "
                "через «+ Новый канал» с той же фразой"
            )
        await self._connect(conversation_id, room_id, prs, timeout=timeout)

    async def _connect(
        self, conv_id: int, room_id: bytes, prs: bytes, *, timeout: float | None = None,
    ) -> None:
        """Общий путь установления канала — первое подключение и реконнект.

        Ждёт пира до ``timeout`` (или ``connect_timeout`` по умолчанию — 5 минут);
        именно за это время должен успеть тоже подключиться собеседник (напр.
        нажать «Выйти на связь» на своей стороне)."""
        wait = timeout or self._connect_timeout
        udp = proto = rv = transport = None
        role = None
        try:
            udp, proto, local = await open_udp_endpoint()
            rv = await RendezvousClient(self._rendezvous_url).join(
                room_id, [local], timeout=wait
            )
            role = rv.role

            async def relay_factory():
                return RelayTransport.from_rendezvous(rv)

            if self._allow_direct:
                transport = await establish_transport(
                    udp, proto, rv.peer_candidates, relay_factory,
                    punch_timeout=self._punch_timeout,
                )
            else:
                udp.close()
                udp = None
                transport = await relay_factory()

            if not isinstance(transport, RelayTransport):
                await rv.close()  # на прямом пути rendezvous больше не нужен
                rv = None

            result = await handshake(transport, prs, role)
            session = open_session(
                self._vault, conv_id, transport, result.sk, result.ratchet_state,
                on_message=lambda body, _cid=conv_id: self._on_message(_cid, body),
                on_disconnect=lambda _cid=conv_id: self._handle_disconnect(_cid),
            )
            session.start()
            self._sessions[conv_id] = session
            self._roles[conv_id] = role
            # INITIATOR праймит ratchet ответчика: шлёт первое (служебное) сообщение,
            # из которого RESPONDER выводит свою отправляющую цепочку (порядок
            # отправки в Double Ratchet). Best-effort — провал не рушит сессию.
            if role == Role.INITIATOR:
                try:
                    await session.send_prime()
                except Exception:
                    pass
            self._on_state_change(conv_id, "connected")
        except Exception as exc:
            # Провал хендшейка/сети: закрыть всё, что успели открыть, иначе
            # утёкшее соединение держит rendezvous-сервер (wait_closed зависнет).
            await _safe_close(transport)
            await _safe_close(rv)
            if udp is not None:
                udp.close()
            self._on_error(conv_id, exc)
            raise

    def _handle_disconnect(self, conversation_id: int) -> None:
        """Сессия сама обнаружила обрыв транспорта (не через ``stop_session``) —
        снять её из активных и оповестить UI, что пир теперь офлайн.

        Зовётся из ``Session._recv_loop`` — та работает как таск на loop-потоке
        сервиса, поэтому состояние (``_sessions``/``_roles``) можно трогать
        напрямую, без ``_submit``."""
        if self._sessions.pop(conversation_id, None) is not None:
            self._roles.pop(conversation_id, None)
            self._on_state_change(conversation_id, "disconnected")

    async def _send(self, conversation_id: int, text: str) -> None:
        session = self._sessions.get(conversation_id)
        if session is None:
            raise KeyError(f"нет активной сессии для беседы {conversation_id}")
        await session.send(text)

    async def _send_file(
        self, conversation_id: int, filename: str, mime_type: str, data: bytes
    ) -> None:
        session = self._sessions.get(conversation_id)
        if session is None:
            raise KeyError(f"нет активной сессии для беседы {conversation_id}")
        await session.send_file(filename, mime_type, data)

    async def _stop_session(self, conversation_id: int) -> None:
        session = self._sessions.pop(conversation_id, None)
        self._roles.pop(conversation_id, None)
        if session is not None:
            await session.close()
            self._on_state_change(conversation_id, "disconnected")
