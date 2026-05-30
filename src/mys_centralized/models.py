"""Модели данных централизованного режима (чистые dataclass-ы, без I/O)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Session:
    """Сессия аккаунта на сервере. Токен чувствителен — на диск только в vault."""

    server_url: str
    username: str
    user_id: int
    token: str


@dataclass
class Room:
    """Комната (диалог/группа) на сервере."""

    id: int
    name: str | None = None
    is_direct: bool = False
    updated_at: str | None = None


@dataclass
class RemoteMessage:
    """Сообщение, как его отдаёт сервер.

    `client_msg_id` присутствует у исходящих (для идемпотентности и дедупа эха).
    """

    id: int
    room_id: int
    sender: str
    body: str
    created_at: str
    client_msg_id: str | None = None


@dataclass
class SyncCursor:
    """Позиция синхронизации по комнате: серверный id последнего загруженного.

    Сериализуется в строку для хранения в settings.
    """

    room_id: int
    last_id: int | None = None

    def to_str(self) -> str:
        return "" if self.last_id is None else str(self.last_id)

    @classmethod
    def from_str(cls, room_id: int, raw: str | None) -> SyncCursor:
        if not raw:
            return cls(room_id=room_id, last_id=None)
        return cls(room_id=room_id, last_id=int(raw))
