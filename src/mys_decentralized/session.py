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
        # Исходящие, накопленные пока нельзя слать (RESPONDER до первого входящего):
        # (local_message_id, plaintext). Флашатся, как только появится cks.
        self._outbox: list[tuple[int, bytes]] = []

    @property
    def can_send(self) -> bool:
        """Есть ли отправляющая цепочка ratchet (у RESPONDER появляется только
        после первого принятого сообщения; см. follow-up порядка отправки)."""
        return self._state.cks is not None

    def start(self) -> None:
        """Запустить фоновый цикл приёма (идемпотентно)."""
        if self._recv_task is None:
            self._running = True
            self._recv_task = asyncio.create_task(self._recv_loop())

    async def send(self, text: str) -> None:
        """Зашифровать и отправить ``text``; после успеха — записать и персистить.

        Если отправляющая цепочка ещё не готова (RESPONDER не принял первого
        сообщения), сообщение записывается как ``pending`` и ставится в очередь —
        будет отправлено автоматически при первом входящем (праймится INITIATOR'ом).
        """
        data = text.encode("utf-8")
        if not data:
            return  # пустой payload зарезервирован под prime — не шлём как контент
        async with self._lock:
            if not self.can_send:
                local_id = self._vault.messages.add(
                    self._conv, direction="out", body=data, status="pending"
                )
                self._outbox.append((local_id, data))
                return
            await self._seal_and_send(data)
            self._vault.messages.add(
                self._conv, direction="out", body=data, status="sent"
            )
            self._vault.ratchet.save_state(self._conv, self._state)

    async def send_prime(self) -> None:
        """Отправить prime-кадр (пустой payload), чтобы продвинуть ratchet пира.

        Шлёт INITIATOR при подключении: даёт RESPONDER'у первое сообщение, из
        которого тот выводит свою отправляющую цепочку. Best-effort и не виден в
        истории. No-op, если своя цепочка ещё не готова."""
        async with self._lock:
            if not self.can_send:
                return
            await self._seal_and_send(b"")
            self._vault.ratchet.save_state(self._conv, self._state)

    async def _seal_and_send(self, data: bytes) -> None:
        """Запечатать payload и отправить в транспорт (вызывать под self._lock)."""
        sealed = envelope.seal(self._state, self._tk, data)
        await self._transport.send(encode_message(Data(sealed)))

    async def _flush_outbox_locked(self) -> None:
        """Отправить накопленные исходящие (вызывать под self._lock, когда есть cks)."""
        if not self._outbox or not self.can_send:
            return
        while self._outbox:
            local_id, data = self._outbox.pop(0)
            await self._seal_and_send(data)
            self._vault.messages.set_status(local_id, "sent")
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
            if plaintext == b"":
                # prime-кадр: продвинул наш ratchet (теперь есть cks), но это не
                # контент — не персистим сообщение, лишь сохраняем состояние.
                self._vault.ratchet.save_state(self._conv, self._state)
            else:
                # Атомарно: входящее сообщение + новое состояние ratchet.
                self._vault.receive_message(
                    self._conv, body=plaintext, new_state=self._state
                )
            # Первое входящее могло открыть отправляющую цепочку — флашим очередь.
            await self._flush_outbox_locked()
        if plaintext != b"" and self._on_message is not None:
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
