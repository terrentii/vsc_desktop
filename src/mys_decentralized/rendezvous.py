"""Клиент rendezvous: вход в комнату и ожидание пары (WebSocket).

Граница CLAUDE.md: клиент обменивается с сервером только сигнализацией
(``HELLO``/``PAIR``) над непрозрачными кадрами — фраза и открытый текст сюда не
попадают. После пейринга то же WS-соединение отдаётся ``RelayTransport`` для
relay-пути (см. :mod:`.transport`).

Транспорт — WebSocket (``ws://``/``wss://``): один порт с веб-сервером,
прокси/TLS-дружелюбно. Каждый кадр — одно бинарное WS-сообщение.
"""

import asyncio
from dataclasses import dataclass

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, WebSocketException

from .errors import PeerUnavailable, RendezvousError
from .protocol import Candidate, Hello, Pair, Role, decode_message, encode_message


@dataclass
class Rendezvous:
    """Результат пейринга: роль, кандидаты пира и живое WS-соединение к серверу."""

    role: Role
    peer_candidates: list[Candidate]
    ws: object

    async def close(self) -> None:
        try:
            await self.ws.close()
        except (ConnectionClosed, OSError):
            pass


class RendezvousClient:
    def __init__(self, url: str):
        """``url`` — адрес WS-эндпоинта rendezvous, напр. ``wss://soufos.ru/p2p``."""
        self._url = url

    async def join(
        self,
        room_id: bytes,
        candidates: list[Candidate],
        timeout: float = 10.0,
    ) -> Rendezvous:
        """Войти в комнату ``room_id`` и дождаться ``PAIR``.

        Таймаут ожидания пира ⇒ :class:`PeerUnavailable` (понятное сообщение в UI).
        """
        try:
            ws = await connect(self._url)
        except (OSError, WebSocketException) as exc:
            raise RendezvousError("не удалось подключиться к rendezvous-серверу") from exc

        await ws.send(encode_message(Hello(room_id, candidates)))
        try:
            message = await asyncio.wait_for(ws.recv(), timeout)
        except asyncio.TimeoutError:
            await ws.close()
            raise PeerUnavailable("пир не вошёл в комнату за отведённый таймаут")
        except ConnectionClosed as exc:
            raise RendezvousError("соединение с rendezvous-сервером оборвалось") from exc

        msg, _consumed = decode_message(message)
        if not isinstance(msg, Pair):
            await ws.close()
            raise RendezvousError("ожидался PAIR от сервера")
        return Rendezvous(msg.role, msg.peer_candidates, ws)
