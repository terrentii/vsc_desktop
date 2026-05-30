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
        rendezvous_addr: tuple[str, int],
        *,
        mode: str = "decentralized",
        on_message: OnMessage | None = None,
        on_state_change: OnStateChange | None = None,
        on_error: OnError | None = None,
        connect_timeout: float = 10.0,
        punch_timeout: float = 1.0,
        allow_direct: bool = True,
    ):
        self._vault = vault
        self._rv_host, self._rv_port = rendezvous_addr
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

        Блокирует до установления канала и хендшейка. Провал PAKE/таймаут пира
        пробрасывается вызывающему (PAKEError/PeerUnavailable) для показа в UI.
        """
        budget = (timeout or self._connect_timeout) + 10.0
        return self._submit(self._start_session(phrase), timeout=budget)

    def send(self, conversation_id: int, text: str, *, timeout: float = 15.0) -> None:
        self._submit(self._send(conversation_id, text), timeout=timeout)

    def stop_session(self, conversation_id: int, *, timeout: float = 10.0) -> None:
        self._submit(self._stop_session(conversation_id), timeout=timeout)

    # --- корутины (исполняются в loop-потоке) ---------------------------------

    def _conversation_for(self, room_id: bytes) -> int:
        for conv in self._vault.conversations.list(self._mode):
            if conv["room_id"] == room_id:
                return conv["id"]
        return self._vault.conversations.add(mode=self._mode, room_id=room_id)

    async def _start_session(self, phrase: str) -> int:
        room_id, prs = derive_room_params(phrase)
        conv_id = self._conversation_for(room_id)
        udp = proto = rv = transport = None
        role = None
        try:
            udp, proto, local = await open_udp_endpoint()
            rv = await RendezvousClient(self._rv_host, self._rv_port).join(
                room_id, [local], timeout=self._connect_timeout
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
            )
            session.start()
            self._sessions[conv_id] = session
            self._roles[conv_id] = role
            self._on_state_change(conv_id, "connected")
            return conv_id
        except Exception as exc:
            # Провал хендшейка/сети: закрыть всё, что успели открыть, иначе
            # утёкшее соединение держит rendezvous-сервер (wait_closed зависнет).
            await _safe_close(transport)
            await _safe_close(rv)
            if udp is not None:
                udp.close()
            self._on_error(conv_id, exc)
            raise

    async def _send(self, conversation_id: int, text: str) -> None:
        session = self._sessions.get(conversation_id)
        if session is None:
            raise KeyError(f"нет активной сессии для беседы {conversation_id}")
        await session.send(text)

    async def _stop_session(self, conversation_id: int) -> None:
        session = self._sessions.pop(conversation_id, None)
        self._roles.pop(conversation_id, None)
        if session is not None:
            await session.close()
            self._on_state_change(conversation_id, "disconnected")
