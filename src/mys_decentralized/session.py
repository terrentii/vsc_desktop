"""Защищённая сессия: Double Ratchet + envelope поверх транспорта, с персистом.

Склейка крипто+сеть+хранилище (граница CLAUDE.md): транспорт даёт непрозрачные
кадры, ratchet/envelope (:mod:`mys_crypto`) дают E2E-шифрование, vault
(:mod:`mys_storage`) хранит сообщения и состояние ratchet per-conversation.

- Отправка: ``DATA{ envelope.seal(...) }`` в транспорт, затем запись исходящего
  и сохранение состояния ratchet. Содержимое внутри ``seal`` тегируется байтом
  kind (:mod:`.filetransfer`) — текст или файловые META/CHUNK кадры; формат
  содержимого, не wire-``MsgType`` (тот не меняется).
- Приём: ``envelope.open_(...)`` → plaintext, атомарная запись через
  ``Vault.receive_message`` (сообщение + новое состояние одной транзакцией).
  Файлы пересобираются в памяти по ``transfer_id`` и персистятся одной строкой
  только после получения всех чанков и проверки sha256 — промежуточные
  META/CHUNK кадры лишь двигают и сохраняют ratchet-state (как prime-кадр).
- Битый/повторённый ``DATA`` отбрасывается (ratchet не двигается), сессия жива.
- Реконнект: если состояние ratchet для комнаты уже в vault — сессия
  **возобновляет** его (PAKE на реконнекте лишь заново аутентифицирует пира);
  первая сессия в комнате сеет ratchet из PAKE (§6 спеки).

Сессия — чистый asyncio без Qt; колбэк ``on_message`` синхронный, маршалинг в UI
делает вышестоящий слой (service/controller).
"""

import asyncio
import hashlib
import os
from collections.abc import Callable

from mys_crypto import envelope

from . import filetransfer
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
        on_disconnect: Callable[[], None] | None = None,
    ):
        self._transport = transport
        self._state = state
        self._tk = transform_key
        self._vault = vault
        self._conv = conversation_id
        self._on_message = on_message
        # Зовётся, только когда транспорт оборвался НЕ через close() (см.
        # _recv_loop) — сигнал «пир пропал», а не штатное закрытие сессии.
        self._on_disconnect = on_disconnect
        self._lock = asyncio.Lock()  # сериализует доступ к ratchet (send vs recv)
        self._recv_task: asyncio.Task | None = None
        self._running = False
        # Исходящие, накопленные пока нельзя слать (RESPONDER до первого входящего):
        # (local_message_id, kind-тегированный payload). Флашатся, как только
        # появится cks. Файлы в очередь не встают — см. send_file().
        self._outbox: list[tuple[int, bytes]] = []
        # Пересборка входящих файлов: transfer_id -> {"meta": FileMeta|None,
        # "chunks": {index: bytes}}. Незавершённые трансферы живут не дольше
        # сессии (см. close()) — best-effort, как и для обычных сообщений.
        self._pending_files: dict[bytes, dict] = {}

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
        payload = bytes([filetransfer.KIND_TEXT]) + data
        async with self._lock:
            if not self.can_send:
                local_id = self._vault.messages.add(
                    self._conv, direction="out", body=data, status="pending"
                )
                self._outbox.append((local_id, payload))
                return
            await self._seal_and_send(payload)
            self._vault.messages.add(
                self._conv, direction="out", body=data, status="sent"
            )
            self._vault.ratchet.save_state(self._conv, self._state)

    async def send_file(self, filename: str, mime_type: str, data: bytes) -> int:
        """Отправить файл (META-кадр + N чанков); вернуть local message id.

        Требует ``can_send`` (RESPONDER до первого входящего не может отправлять
        файлы в v1 — бросает ``RuntimeError``; в отличие от ``send()``, файл в
        ``_outbox`` не ставится: очередь рассчитана на цельные независимые
        сообщения, а файл — упорядоченная группа кадров, расширять очередь под
        групповую семантику ради узкого предпраймингового окна не стоит).

        Состояние ratchet сохраняется после КАЖДОГО отправленного кадра (не
        только в конце): цепочка отправки двигается на каждый ``envelope.seal``,
        и если процесс упадёт посреди передачи, при рестарте нельзя воскресить
        стухший ``cks`` — это привело бы к повторному использованию уже
        использованного ключа ratchet.
        """
        if len(data) > filetransfer.MAX_FILE_SIZE:
            raise ValueError(f"файл превышает лимит {filetransfer.MAX_FILE_SIZE} байт")
        async with self._lock:
            if not self.can_send:
                raise RuntimeError(
                    "канал ещё не готов для отправки файла (примите первое сообщение)"
                )
            transfer_id = os.urandom(filetransfer.TRANSFER_ID_LEN)
            chunks = filetransfer.split_chunks(data)
            meta = filetransfer.FileMeta(
                transfer_id=transfer_id,
                total_size=len(data),
                chunk_size=filetransfer.CHUNK_SIZE,
                chunk_count=len(chunks),
                sha256=hashlib.sha256(data).digest(),
                mime_type=mime_type,
                filename=filename,
            )
            meta_payload = bytes([filetransfer.KIND_FILE_META]) + filetransfer.encode_file_meta(meta)
            await self._seal_and_send(meta_payload)
            self._vault.ratchet.save_state(self._conv, self._state)
            for idx, chunk in enumerate(chunks):
                fc = filetransfer.FileChunk(transfer_id=transfer_id, index=idx, data=chunk)
                chunk_payload = bytes([filetransfer.KIND_FILE_CHUNK]) + filetransfer.encode_file_chunk(fc)
                await self._seal_and_send(chunk_payload)
                self._vault.ratchet.save_state(self._conv, self._state)
            local_id = self._vault.messages.add(
                self._conv, direction="out", body=data, status="sent",
                kind=filetransfer.kind_for_filename(filename),
                filename=filename, mime_type=mime_type,
            )
        return local_id

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
            # Обрыв транспорта САМ ПО СЕБЕ (не через close(), тот отменяет задачу
            # через CancelledError, сюда не попадает) — пир пропал. Транспорт
            # мог остаться формально ОТКРЫТЫМ (напр. PEER_LEFT от сервера: наш
            # собственный WS до сервера жив, ушёл только пир) — закрываем сами,
            # иначе соединение зависает навсегда и комната на сервере никогда
            # не опустеет. close() у транспортов идемпотентен (повторный вызов
            # из Session.close(), если её всё же позовут следом, безопасен).
            try:
                await self._transport.close()
            except Exception:
                pass
            # Оповестить вышестоящий слой (P2PService), чтобы он снял «онлайн»
            # и убрал мёртвую сессию из активных. Best-effort: колбэк не должен
            # ронять цикл приёма, если сам бросит исключение.
            if self._on_disconnect is not None:
                try:
                    self._on_disconnect()
                except Exception:
                    pass

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
            persist = None  # (kind, filename, mime_type, body) | None
            if plaintext == b"":
                # prime-кадр: продвинул наш ratchet (теперь есть cks), но это не
                # контент — не персистим сообщение, лишь сохраняем состояние.
                self._vault.ratchet.save_state(self._conv, self._state)
            else:
                try:
                    persist = self._dispatch_content(plaintext)
                except Exception:
                    # битый/невалидный файловый кадр — отбросить, как и
                    # обычный DATA-кадр выше; сессия жива, ratchet уже
                    # продвинут (decrypt прошёл), состояние всё же сохраняем.
                    persist = None
                if persist is None:
                    self._vault.ratchet.save_state(self._conv, self._state)
                else:
                    kind, filename, mime_type, body = persist
                    self._vault.receive_message(
                        self._conv, body=body, new_state=self._state,
                        kind=kind, filename=filename, mime_type=mime_type,
                    )
            # Первое входящее могло открыть отправляющую цепочку — флашим очередь.
            await self._flush_outbox_locked()
        if persist is not None and self._on_message is not None:
            self._on_message(persist[3])

    def _dispatch_content(self, plaintext: bytes):
        """Разобрать kind-тегированный plaintext; вернуть persist-кортеж или
        ``None``, если это ещё не завершённый файловый трансфер (или прайм,
        сюда не попадающий — см. вызывающий код)."""
        kind, body = plaintext[0], plaintext[1:]
        if kind == filetransfer.KIND_TEXT:
            return ("text", None, None, body)
        if kind == filetransfer.KIND_FILE_META:
            return self._on_file_meta(body)
        if kind == filetransfer.KIND_FILE_CHUNK:
            return self._on_file_chunk(body)
        return None  # неизвестный kind — форвард-совместимость, тихо отбросить

    def _on_file_meta(self, body: bytes):
        meta = filetransfer.decode_file_meta(body)
        filetransfer.validate_meta(meta)
        entry = self._pending_files.setdefault(
            meta.transfer_id, {"meta": None, "chunks": {}}
        )
        entry["meta"] = meta
        return self._maybe_complete(meta.transfer_id)

    def _on_file_chunk(self, body: bytes):
        chunk = filetransfer.decode_file_chunk(body)
        entry = self._pending_files.setdefault(
            chunk.transfer_id, {"meta": None, "chunks": {}}
        )
        entry["chunks"][chunk.index] = chunk.data
        return self._maybe_complete(chunk.transfer_id)

    def _maybe_complete(self, transfer_id: bytes):
        entry = self._pending_files.get(transfer_id)
        if entry is None or entry["meta"] is None:
            return None
        meta = entry["meta"]
        if len(entry["chunks"]) < meta.chunk_count:
            return None  # ждём ещё чанки (порядок прихода не важен)
        try:
            full = b"".join(entry["chunks"][i] for i in range(meta.chunk_count))
        except KeyError:
            return None  # дубли/пропуски вместо честного набора 0..chunk_count-1
        del self._pending_files[transfer_id]
        if hashlib.sha256(full).digest() != meta.sha256:
            return None  # повреждённый трансфер — отбросить, сессия жива
        return ("file", meta.filename, meta.mime_type, full)

    async def close(self) -> None:
        self._running = False
        if self._recv_task is not None:
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass
            self._recv_task = None
        self._pending_files.clear()
        await self._transport.close()


def open_session(
    vault,
    conversation_id: int,
    transport: Transport,
    sk: bytes,
    seed_state,
    on_message: OnMessage | None = None,
    on_disconnect: Callable[[], None] | None = None,
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
    return Session(
        transport, state, transform_key, vault, conversation_id, on_message,
        on_disconnect,
    )
