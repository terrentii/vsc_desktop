"""Централизованный модуль (под-проект №6): REST + WebSocket клиент, синк.

Клиент к серверу `soufos.ru` (`vsc_web`). Проектируется под целевой контракт
«токен + WebSocket». Не импортирует Qt; экспонирует API для `mys_ui`.
"""

from .errors import (
    AuthError,
    CentralizedError,
    NetworkError,
    ProtocolError,
    ServerError,
)
from .models import RemoteMessage, Room, Session, SyncCursor

__all__ = [
    "CentralizedError",
    "AuthError",
    "ServerError",
    "NetworkError",
    "ProtocolError",
    "Session",
    "Room",
    "RemoteMessage",
    "SyncCursor",
]
