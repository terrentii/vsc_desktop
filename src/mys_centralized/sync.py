"""Движок синхронизации централизованного режима.

Связывает REST/WS-данные с зашифрованным vault: upsert комнат в conversations,
дозагрузка истории по курсору, дедуп (серверный id + client_msg_id), отправка с
идемпотентностью. Курсор продвигается только в `sync_history` (авторитетная
последовательная дозагрузка), чтобы реконнект закрывал пропуски без потерь;
live-кадры WS лишь персистятся и дедупятся по серверному id.
"""

from __future__ import annotations

import uuid

from .models import RemoteMessage

MODE = "centralized"


def _room_key(server_room_id: int) -> bytes:
    return str(int(server_room_id)).encode("utf-8")


def _cursor_key(server_room_id: int) -> str:
    return f"central.cursor.{int(server_room_id)}"


class SyncEngine:
    def __init__(self, vault, rest, *, on_message=None, page_limit: int = 200):
        self._vault = vault
        self._rest = rest
        self._on_message = on_message  # callback(conv_id, local_id, RemoteMessage)
        self._page_limit = page_limit

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
        )
        return self._ingest(conv_id, msg)

    async def send(self, conv_id, body: str):
        """Отправить сообщение: pending → POST (идемпотентно) → sent / failed."""
        server_room_id = self._server_room_of(conv_id)
        client_msg_id = uuid.uuid4().hex
        local_id = self._vault.messages.add(
            conv_id, direction="out", body=body.encode("utf-8"),
            status="pending", client_msg_id=client_msg_id,
        )
        try:
            msg = await self._rest.post_message(server_room_id, body, client_msg_id)
        except Exception:
            self._vault.messages.set_status(local_id, "failed")
            raise
        self._vault.messages.mark_sent(local_id, wire_seq=msg.id)
        return local_id

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
        local_id = self._vault.receive_message(
            conv_id, body=msg.body.encode("utf-8"), direction="in",
            status="received", wire_seq=msg.id,
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
