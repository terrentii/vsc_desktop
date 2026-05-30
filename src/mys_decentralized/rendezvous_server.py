"""Минимальный rendezvous-сервер: пейринг по ``room_id`` и relay-ретрансляция.

Фикстура интеграционных тестов и референс для реализации в ``vsc_web`` (№5).
Сервер видит только ``room_id`` и непрозрачный payload ``RELAY`` — фразы и
открытого текста не знает, payload не читает (граница безопасности, CLAUDE.md):
первый вошедший — ``INITIATOR``, второй — ``RESPONDER``; роли назначаются
детерминированно по порядку входа.
"""

import asyncio
from dataclasses import dataclass

from .protocol import Hello, Pair, Relay, Role, decode_message, encode_message
from .transport import read_frame, write_frame


@dataclass
class _Member:
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    role: Role
    candidates: list


class RendezvousServer:
    def __init__(self) -> None:
        self._rooms: dict[bytes, list[_Member]] = {}
        self._server: asyncio.AbstractServer | None = None

    async def start(self, host: str = "127.0.0.1", port: int = 0) -> tuple[str, int]:
        self._server = await asyncio.start_server(self._handle, host, port)
        sock = self._server.sockets[0].getsockname()
        return sock[0], sock[1]

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    def _peer_of(self, room_id: bytes, member: _Member) -> _Member | None:
        for other in self._rooms.get(room_id, ()):
            if other is not member:
                return other
        return None

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        room_id: bytes | None = None
        member: _Member | None = None
        try:
            hello_frame = await read_frame(reader)
            hello, _ = decode_message(hello_frame)
            if not isinstance(hello, Hello):
                return  # первый кадр обязан быть HELLO
            room_id = hello.room_id
            room = self._rooms.setdefault(room_id, [])
            if len(room) >= 2:
                return  # комната занята (v1: только 1:1)

            role = Role.INITIATOR if not room else Role.RESPONDER
            member = _Member(reader, writer, role, hello.candidates)
            room.append(member)

            if len(room) == 2:
                first, second = room
                await write_frame(
                    first.writer, encode_message(Pair(first.role, second.candidates))
                )
                await write_frame(
                    second.writer, encode_message(Pair(second.role, first.candidates))
                )

            # Ретрансляция: RELAY-кадр пересылается пиру в комнате как есть.
            while True:
                frame = await read_frame(reader)
                msg, _ = decode_message(frame)
                if isinstance(msg, Relay):
                    peer = self._peer_of(room_id, member)
                    if peer is not None:
                        await write_frame(peer.writer, frame)
        except Exception:
            # Обрыв/битый кадр — просто закрываем соединение и чистим комнату.
            pass
        finally:
            if room_id is not None and member is not None:
                room = self._rooms.get(room_id)
                if room is not None and member in room:
                    room.remove(member)
                    if not room:
                        self._rooms.pop(room_id, None)
            writer.close()
