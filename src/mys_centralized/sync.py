"""Движок синхронизации централизованного режима.

Связывает REST/WS-данные с зашифрованным vault: upsert комнат в conversations,
дозагрузка истории по курсору, дедуп (серверный id + client_msg_id), отправка с
идемпотентностью. Курсор продвигается только в `sync_history` (авторитетная
последовательная дозагрузка), чтобы реконнект закрывал пропуски без потерь;
live-кадры WS лишь персистятся и дедупятся по серверному id.
"""

from __future__ import annotations

import mimetypes
import uuid
from datetime import datetime, timezone

from . import media
from .models import RemoteMessage

MODE = "centralized"


def _epoch_of(created_at) -> float | None:
    """Серверный ISO `created_at` (наивный = UTC, см. серверную спеку) → epoch.

    Непарсибельное значение — None (хранилище подставит локальные часы)."""
    try:
        dt = datetime.fromisoformat(str(created_at))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _room_key(server_room_id: int) -> bytes:
    return str(int(server_room_id)).encode("utf-8")


def _cursor_key(server_room_id: int) -> str:
    return f"central.cursor.{int(server_room_id)}"


class SyncEngine:
    def __init__(self, vault, rest, *, on_message=None, page_limit: int = 200,
                 own_username: str | None = None):
        self._vault = vault
        self._rest = rest
        self._on_message = on_message  # callback(conv_id, local_id, RemoteMessage)
        self._page_limit = page_limit
        self._own_username = own_username  # для дедупа собственного эха без client_msg_id

    # -- сопоставление комнат и бесед --------------------------------------

    def _conv_for_room(self, server_room_id: int, *, name=None, create: bool = True):
        key = _room_key(server_room_id)
        row = self._vault.conversations.get_by_room_id(key, mode=MODE)
        if row is not None:
            return row["id"]
        if not create:
            return None
        return self._vault.conversations.add(mode=MODE, room_id=key, title=name)

    def _server_room_of(self, conv_id) -> int:
        row = self._vault.conversations.get(conv_id)
        rid = row["room_id"]
        if isinstance(rid, bytes):
            rid = rid.decode("utf-8")
        return int(rid)

    # -- синхронизация -----------------------------------------------------

    async def sync_rooms(self) -> dict[int, int]:
        """Загрузить список комнат, upsert в conversations. Возвращает {room_id: conv_id}."""
        rooms = await self._rest.list_rooms()
        return {r.id: self._conv_for_room(r.id, name=r.name) for r in rooms}

    async def create_room(self, name: str) -> int:
        """Создать комнату на сервере и завести/найти локальную беседу. → conv_id."""
        room = await self._rest.create_room(name)
        return self._conv_for_room(room.id, name=room.name)

    async def sync_history(self, server_room_id: int):
        """Дозагрузить историю комнаты от текущего курсора страницами."""
        conv_id = self._conv_for_room(server_room_id)
        cursor = self._get_cursor(server_room_id)
        while True:
            msgs, next_cursor = await self._rest.get_messages(
                server_room_id, after=cursor, limit=self._page_limit
            )
            if not msgs:
                break
            high = cursor or 0
            for m in msgs:
                self._ingest(conv_id, m)
                high = max(high, m.id)
            self._set_cursor(server_room_id, high)
            cursor = high
            if next_cursor is None:
                break
            cursor = next_cursor
        return conv_id

    async def sync_all(self) -> dict[int, int]:
        """Полный цикл: комнаты + история по каждой."""
        mapping = await self.sync_rooms()
        for server_room_id in mapping:
            await self.sync_history(server_room_id)
        return mapping

    async def ingest_ws(self, frame: dict):
        """Принять live-кадр `message` из WebSocket: персист + дедуп."""
        server_room_id = int(frame["room_id"])
        conv_id = self._conv_for_room(server_room_id)
        msg = RemoteMessage(
            id=int(frame["id"]),
            room_id=server_room_id,
            sender=frame["sender"],
            body=frame["body"],
            created_at=frame["created_at"],
            client_msg_id=frame.get("client_msg_id"),
            media=frame.get("media"),
            reply=frame.get("reply_to") or None,
        )
        return self._ingest(conv_id, msg)

    def apply_ws_edit(self, frame: dict):
        """Live-правка с сервера: обновить тело по серверному id. → conv_id | None."""
        conv_id = self._conv_for_room(int(frame["room_id"]), create=False)
        if conv_id is None:
            return None
        row = self._vault.messages.find_by_wire(conv_id, int(frame["id"]))
        if row is None:
            return None
        self._vault.messages.set_body(row["id"], str(frame.get("body") or "").encode("utf-8"))
        return conv_id

    def apply_ws_delete(self, frame: dict):
        """Live-удаление с сервера: убрать строку по серверному id. → conv_id | None."""
        conv_id = self._conv_for_room(int(frame["room_id"]), create=False)
        if conv_id is None:
            return None
        row = self._vault.messages.find_by_wire(conv_id, int(frame["id"]))
        if row is None:
            return None
        self._vault.messages.delete(row["id"])
        return conv_id

    def _notify(self, conv_id, local_id) -> None:
        """Сигнал UI «строка появилась/изменила статус» (оптимистичная отправка)."""
        if self._on_message is not None:
            self._on_message(conv_id, local_id, None)

    async def send(self, conv_id, body: str, *, reply: dict | None = None):
        """Отправить сообщение: pending → POST (идемпотентно) → sent / failed.

        ``reply`` — {"wire": <server id>, "sender": ..., "snippet": ...}: серверу
        уходит id, локально сразу сохраняется готовая цитата. UI уведомляется на
        каждом переходе статуса — pending-строка видна мгновенно, до ответа
        сервера (оптимистичная отправка)."""
        server_room_id = self._server_room_of(conv_id)
        client_msg_id = uuid.uuid4().hex
        reply = reply or {}
        local_id = self._vault.messages.add(
            conv_id, direction="out", body=body.encode("utf-8"),
            status="pending", client_msg_id=client_msg_id,
            reply_author=reply.get("sender"), reply_snippet=reply.get("snippet"),
        )
        self._notify(conv_id, local_id)
        try:
            msg = await self._rest.post_message(
                server_room_id, body, client_msg_id, reply_to=reply.get("wire")
            )
        except Exception:
            self._vault.messages.set_status(local_id, "failed")
            self._notify(conv_id, local_id)
            raise
        self._vault.messages.mark_sent(local_id, wire_seq=msg.id)
        self._notify(conv_id, local_id)
        return local_id

    async def edit(self, message_id: int, body: str) -> None:
        """Изменить своё сообщение: REST → локальное тело."""
        row = self._vault.messages.get(message_id)
        if row is None:
            raise ValueError("сообщение не найдено")
        if row["wire_seq"] is None:
            raise ValueError("сообщение ещё не подтверждено сервером")
        await self._rest.edit_message(row["wire_seq"], body)
        self._vault.messages.set_body(message_id, body.encode("utf-8"))

    async def delete(self, message_id: int) -> None:
        """Удалить своё сообщение: REST → локальная строка."""
        row = self._vault.messages.get(message_id)
        if row is None:
            return
        if row["wire_seq"] is None:
            raise ValueError("сообщение ещё не подтверждено сервером")
        await self._rest.delete_message(row["wire_seq"])
        self._vault.messages.delete(message_id)

    async def send_file(self, conv_id, filename: str, mime_type: str, data: bytes) -> int:
        """Загрузить файл, затем отправить сообщение со ссылкой на него.

        Тело у нас уже в памяти — сохраняем сразу (не ленивая докачка, та
        нужна только для чужих/исторических вложений, см. ``fetch_media``).
        """
        if len(data) > media.MAX_MEDIA_SIZE:
            raise ValueError(f"файл больше {media.MAX_MEDIA_SIZE // (1024 * 1024)} МБ")
        media.validate_extension(filename)
        server_room_id = self._server_room_of(conv_id)
        upload = await self._rest.upload_media(server_room_id, filename, data, mime_type)
        client_msg_id = uuid.uuid4().hex
        local_id = self._vault.messages.add(
            conv_id, direction="out", body=data, status="pending",
            client_msg_id=client_msg_id, kind=media.kind_for_filename(filename),
            filename=filename, mime_type=mime_type, media_ref=upload["filename"],
        )
        try:
            msg = await self._rest.post_message(
                server_room_id, "", client_msg_id, media=upload["filename"]
            )
        except Exception:
            self._vault.messages.set_status(local_id, "failed")
            raise
        self._vault.messages.mark_sent(local_id, wire_seq=msg.id)
        return local_id

    async def fetch_media(self, message_id: int) -> bytes:
        """Докачать байты вложения (ленивая загрузка) и закэшировать в vault."""
        row = self._vault.messages.get(message_id)
        if row is None:
            raise ValueError("сообщение не найдено")
        if row["body"] is not None:
            return row["body"]
        if row["media_ref"] is None:
            raise ValueError("нет вложения")
        server_room_id = self._server_room_of(row["conversation_id"])
        data, _mime = await self._rest.download_media(server_room_id, row["media_ref"])
        self._vault.messages.set_body(message_id, data)
        return data

    # -- дедуп и персист ---------------------------------------------------

    def _ingest(self, conv_id, msg: RemoteMessage):
        if self._vault.messages.exists_wire(conv_id, msg.id):
            return None  # уже сохранено (по серверному id)
        if msg.client_msg_id:
            pending = self._vault.messages.find_out_by_client_id(conv_id, msg.client_msg_id)
            if pending is not None:
                # наше собственное эхо — связываем серверный id с исходящей записью
                if pending["wire_seq"] is None:
                    self._vault.messages.mark_sent(pending["id"], wire_seq=msg.id)
                return None
        if self._own_username is not None and msg.sender == self._own_username:
            # Эхо собственного сообщения, в котором сервер не вернул client_msg_id
            # (WS-кадр): связываем по телу с неподтверждённым исходящим, иначе
            # получили бы дубликат-«входящее» из-за гонки POST-ответа и WS-эха.
            body = msg.body.encode("utf-8")
            pending = self._vault.messages.find_unconfirmed_out_by_body(conv_id, body)
            if pending is not None:
                self._vault.messages.mark_sent(pending["id"], wire_seq=msg.id)
                return None
        when = _epoch_of(msg.created_at)
        reply = msg.reply or {}
        if msg.media:
            filename = media.display_name(msg.media)
            local_id = self._vault.messages.add(
                conv_id, direction="in", body=None, status="received", wire_seq=msg.id,
                sender=msg.sender, kind=media.kind_for_filename(msg.media),
                filename=filename, mime_type=mimetypes.guess_type(filename)[0],
                media_ref=msg.media, timestamp=when,
                reply_author=reply.get("sender"), reply_snippet=reply.get("body"),
            )
        else:
            local_id = self._vault.messages.add(
                conv_id, direction="in", body=msg.body.encode("utf-8"),
                status="received", wire_seq=msg.id, sender=msg.sender,
                timestamp=when,
                reply_author=reply.get("sender"), reply_snippet=reply.get("body"),
            )
        if self._on_message is not None:
            self._on_message(conv_id, local_id, msg)
        return local_id

    # -- курсоры -----------------------------------------------------------

    def _get_cursor(self, server_room_id: int):
        raw = self._vault.settings.get(_cursor_key(server_room_id))
        if not raw:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return int(raw)

    def _set_cursor(self, server_room_id: int, value) -> None:
        if value:
            self._vault.settings.set(_cursor_key(server_room_id), str(value).encode("utf-8"))
