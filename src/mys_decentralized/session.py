"""Защищённая сессия: Double Ratchet + envelope поверх транспорта, с персистом.

Склейка крипто+сеть+хранилище (граница CLAUDE.md): транспорт даёт непрозрачные
кадры, ratchet/envelope (:mod:`mys_crypto`) дают E2E-шифрование, vault
(:mod:`mys_storage`) хранит сообщения и состояние ratchet per-conversation.

- Отправка: ``DATA{ envelope.seal(...) }`` в транспорт, затем запись исходящего
  и сохранение состояния ratchet.
- Приём: ``envelope.open_(...)`` → plaintext, атомарная запись через
  ``Vault.receive_message`` (сообщение + новое состояние одной транзакцией).
- Битый/повторённый ``DATA`` отбрасывается (ratchet не двигается), сессия жива.
- Реконнект: если состояние ratchet для комнаты уже в vault — сессия
  **возобновляет** его (PAKE на реконнекте лишь заново аутентифицирует пира);
  первая сессия в комнате сеет ratchet из PAKE (§6 спеки).

Сессия — чистый asyncio без Qt; колбэк ``on_message`` синхронный, маршалинг в UI
делает вышестоящий слой (service/controller).
"""

import asyncio
from collections.abc import Callable

from mys_crypto import envelope

from .errors import TransportError
from .protocol import Data, decode_message, encode_message
from .transport import Transport

OnMessage = Callable[[bytes], None]


class Session:
    """Двунаправленный E2E-канал над одним транспортом и одной беседой vault."""

    def __init__(
        self,
        transport: Transport,
        state,
        transform_key: bytes,
        vault,
        conversation_id: int,
        on_message: OnMessage | None = None,
    ):
        self._transport = transport
        self._state = state
        self._tk = transform_key
        self._vault = vault
        self._conv = conversation_id
        self._on_message = on_message
        self._lock = asyncio.Lock()  # сериализует доступ к ratchet (send vs recv)
        self._recv_task: asyncio.Task | None = None
        self._running = False

    def start(self) -> None:
        """Запустить фоновый цикл приёма (идемпотентно)."""
        if self._recv_task is None:
            self._running = True
            self._recv_task = asyncio.create_task(self._recv_loop())

    async def send(self, text: str) -> None:
        """Зашифровать и отправить ``text``; после успеха — записать и персистить."""
        data = text.encode("utf-8")
        async with self._lock:
            sealed = envelope.seal(self._state, self._tk, data)
            await self._transport.send(encode_message(Data(sealed)))
            self._vault.messages.add(
                self._conv, direction="out", body=data, status="sent"
            )
            self._vault.ratchet.save_state(self._conv, self._state)

    async def _recv_loop(self) -> None:
        try:
            while self._running:
                frame = await self._transport.recv()
                await self._handle_frame(frame)
        except TransportError:
            pass  # транспорт закрыт/оборван — выходим из цикла

    async def _handle_frame(self, frame: bytes) -> None:
        try:
            msg, _consumed = decode_message(frame)
        except TransportError:
            return  # битый кадр — отбросить, сессия жива
        if not isinstance(msg, Data):
            return
        async with self._lock:
            try:
                plaintext = envelope.open_(self._state, self._tk, msg.sealed)
            except Exception:
                # битый sealed или replay: ratchet не двинулся (decrypt атомарен),
                # сессия продолжает работать.
                return
            # Атомарно: входящее сообщение + новое состояние ratchet.
            self._vault.receive_message(
                self._conv, body=plaintext, new_state=self._state
            )
        if self._on_message is not None:
            self._on_message(plaintext)

    async def close(self) -> None:
        self._running = False
        if self._recv_task is not None:
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass
            self._recv_task = None
        await self._transport.close()


def open_session(
    vault,
    conversation_id: int,
    transport: Transport,
    sk: bytes,
    seed_state,
    on_message: OnMessage | None = None,
) -> Session:
    """Собрать сессию, возобновив или посеяв ratchet (ветка реконнекта, §6).

    ``transform_key`` всегда выводится из текущего ``sk`` (обе стороны после PAKE
    согласованы). ``seed_state`` (свежий ratchet из хендшейка) используется только
    если в vault ещё нет состояния для этой беседы; иначе ratchet **возобновляется**
    из vault.
    """
    transform_key = envelope.derive_transform_key(sk)
    existing = vault.ratchet.load_state(conversation_id)
    if existing is not None:
        state = existing
    else:
        state = seed_state
        vault.ratchet.save_state(conversation_id, state)
    return Session(transport, state, transform_key, vault, conversation_id, on_message)
