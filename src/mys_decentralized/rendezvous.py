"""Клиент rendezvous: вход в комнату и ожидание пары.

Граница CLAUDE.md: клиент обменивается с сервером только сигнализацией
(``HELLO``/``PAIR``) над непрозрачными кадрами — фраза и открытый текст сюда не
попадают. После пейринга то же соединение отдаётся ``RelayTransport`` для
relay-пути (см. :mod:`.transport`).
"""

import asyncio
from dataclasses import dataclass

from .errors import PeerUnavailable, RendezvousError, TransportError
from .protocol import Candidate, Hello, Pair, Role, decode_message, encode_message
from .transport import read_frame, write_frame


@dataclass
class Rendezvous:
    """Результат пейринга: роль, кандидаты пира и живое соединение к серверу."""

    role: Role
    peer_candidates: list[Candidate]
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter

    async def close(self) -> None:
        self.writer.close()
        try:
            await self.writer.wait_closed()
        except (ConnectionError, OSError):
            pass


class RendezvousClient:
    def __init__(self, host: str, port: int):
        self._host = host
        self._port = port

    async def join(
        self,
        room_id: bytes,
        candidates: list[Candidate],
        timeout: float = 10.0,
    ) -> Rendezvous:
        """Войти в комнату ``room_id`` и дождаться ``PAIR``.

        Таймаут ожидания пира ⇒ :class:`PeerUnavailable` (понятное сообщение в UI).
        """
        reader, writer = await asyncio.open_connection(self._host, self._port)
        await write_frame(writer, encode_message(Hello(room_id, candidates)))
        try:
            frame = await asyncio.wait_for(read_frame(reader), timeout)
        except asyncio.TimeoutError:
            writer.close()
            raise PeerUnavailable("пир не вошёл в комнату за отведённый таймаут")
        except TransportError:
            writer.close()
            raise RendezvousError("соединение с rendezvous-сервером оборвалось")

        msg, _consumed = decode_message(frame)
        if not isinstance(msg, Pair):
            writer.close()
            raise RendezvousError("ожидался PAIR от сервера")
        return Rendezvous(msg.role, msg.peer_candidates, reader, writer)
