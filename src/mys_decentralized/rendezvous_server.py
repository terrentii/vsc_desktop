"""Минимальный rendezvous-сервер на WebSocket: пейринг по ``room_id`` и relay.

Фикстура интеграционных тестов и референс для реализации в ``vsc_web`` (№5).
Сервер видит только ``room_id`` и непрозрачный payload ``RELAY`` — фразы и
открытого текста не знает, payload не читает (граница безопасности, CLAUDE.md):
первый вошедший в комнату — ``INITIATOR``, второй — ``RESPONDER``; роли
назначаются детерминированно по порядку входа.

Каждый кадр :mod:`.protocol` — одно бинарное WS-сообщение. Семантика кадров
переносится в ``vsc_web`` без изменений.
"""

from dataclasses import dataclass

from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

from .errors import TransportError
from .protocol import Hello, Pair, PeerLeft, Relay, Role, decode_message, encode_message


@dataclass
class _Member:
    ws: object
    role: Role
    candidates: list


class RendezvousServer:
    def __init__(self) -> None:
        self._rooms: dict[bytes, list[_Member]] = {}
        self._server = None

    async def start(self, host: str = "127.0.0.1", port: int = 0) -> tuple[str, int]:
        self._server = await serve(self._handle, host, port)
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

    async def _handle(self, ws) -> None:
        room_id: bytes | None = None
        member: _Member | None = None
        try:
            hello, _ = decode_message(await ws.recv())
            if not isinstance(hello, Hello):
                return  # первое сообщение обязано быть HELLO
            room_id = hello.room_id
            room = self._rooms.setdefault(room_id, [])
            if len(room) >= 2:
                return  # комната занята (v1: только 1:1)

            role = Role.INITIATOR if not room else Role.RESPONDER
            member = _Member(ws, role, hello.candidates)
            room.append(member)

            if len(room) == 2:
                first, second = room
                await first.ws.send(
                    encode_message(Pair(first.role, second.candidates))
                )
                await second.ws.send(
                    encode_message(Pair(second.role, first.candidates))
                )

            # Ретрансляция: RELAY-сообщение пересылается пиру в комнате как есть.
            async for message in ws:
                msg, _ = decode_message(message)
                if isinstance(msg, Relay):
                    peer = self._peer_of(room_id, member)
                    if peer is not None:
                        await peer.ws.send(message)
        except (ConnectionClosed, TransportError):
            pass  # обрыв/битый кадр — закрываем соединение и чистим комнату
        finally:
            if room_id is not None and member is not None:
                room = self._rooms.get(room_id)
                if room is not None and member in room:
                    room.remove(member)
                    # Оставшийся участник узнаёт об уходе пира явно — иначе его
                    # собственное WS-соединение с сервером продолжает жить как
                    # ни в чём не бывало (relay лишь перестаёт получать кадры),
                    # и «онлайн»-статус на его стороне навсегда завис бы в True.
                    for other in room:
                        try:
                            await other.ws.send(encode_message(PeerLeft()))
                        except ConnectionClosed:
                            pass
                    if not room:
                        self._rooms.pop(room_id, None)
