"""Транспорт: доставка непрозрачных кадров пиру.

Граница CLAUDE.md: транспорт ничего не знает о шифровании — он переносит
непрозрачные ``bytes`` (готовые wire-сообщения из :mod:`.protocol`) от одного
пира к другому. Слои ``handshake``/``session`` кладут поверх CPace/ratchet/AEAD.

Здесь: ABC ``Transport``, in-memory дуплекс для тестов, ``RelayTransport``
(путь через rendezvous-сервер по WebSocket). Прямой канал — WebRTC
(:mod:`.webrtc`) поверх уже установленной сессии.

Транспорт rendezvous/relay — WebSocket (один порт с веб-сервером, WSS/прокси-
дружелюбно): каждый wire-кадр :mod:`.protocol` отправляется как одно бинарное
WS-сообщение (границы сообщений сохраняет сам WebSocket).
"""

import asyncio
from abc import ABC, abstractmethod

from websockets.exceptions import ConnectionClosed

from .errors import TransportError
from .protocol import PeerLeft, Relay, decode_message, encode_message



class Transport(ABC):
    """Двунаправленный канал непрозрачных кадров к одному пиру."""

    @abstractmethod
    async def send(self, data: bytes) -> None:
        """Отправить один непрозрачный кадр пиру."""

    @abstractmethod
    async def recv(self) -> bytes:
        """Получить один непрозрачный кадр от пира (ждёт при необходимости)."""

    @abstractmethod
    async def close(self) -> None:
        """Закрыть канал; последующие ``recv`` поднимают ``TransportError``."""


class InMemoryTransport(Transport):
    """Транспорт поверх двух ``asyncio.Queue`` — без сети.

    Используется в тестах хендшейка/сессии и как образец семантики: ``send``
    кладёт кадр во входящую очередь пира, ``recv`` снимает со своей. Создавать
    через :meth:`connected_pair`.
    """

    def __init__(self, inbound: asyncio.Queue, outbound: asyncio.Queue):
        self._inbound = inbound
        self._outbound = outbound
        self._closed = False

    @classmethod
    def connected_pair(cls) -> tuple["InMemoryTransport", "InMemoryTransport"]:
        a_to_b: asyncio.Queue = asyncio.Queue()
        b_to_a: asyncio.Queue = asyncio.Queue()
        a = cls(inbound=b_to_a, outbound=a_to_b)
        b = cls(inbound=a_to_b, outbound=b_to_a)
        return a, b

    async def send(self, data: bytes) -> None:
        if self._closed:
            raise TransportError("send в закрытый транспорт")
        await self._outbound.put(data)

    async def recv(self) -> bytes:
        item = await self._inbound.get()
        if item is _CLOSED:
            raise TransportError("транспорт закрыт")
        return item

    async def close(self) -> None:
        self._closed = True
        await self._outbound.put(_CLOSED)


_CLOSED = object()  # сентинел «канал закрыт» во входящей очереди


# --- relay-first путь через сервер (WebSocket) -------------------------------

class RelayTransport(Transport):
    """Кадры идут на rendezvous-сервер в ``RELAY{payload}`` одним бинарным
    WS-сообщением; сервер пересылает их второму пиру в комнате, **не читая**
    payload (он уже E2E-защищён)."""

    def __init__(self, ws):
        self._ws = ws
        self._closed = False

    @classmethod
    def from_rendezvous(cls, rv) -> "RelayTransport":
        """Построить relay-транспорт поверх уже спаренного WS-соединения."""
        return cls(rv.ws)

    async def send(self, data: bytes) -> None:
        if self._closed:
            raise TransportError("send в закрытый relay")
        try:
            await self._ws.send(encode_message(Relay(data)))
        except ConnectionClosed as exc:
            raise TransportError("relay-соединение закрыто") from exc

    async def recv(self) -> bytes:
        try:
            message = await self._ws.recv()
        except ConnectionClosed as exc:
            raise TransportError("relay-соединение закрыто") from exc
        msg, _consumed = decode_message(message)
        if isinstance(msg, PeerLeft):
            # Сервер сигналит уход пира отдельным кадром (не RELAY, не от пира —
            # само соединение с сервером живо). Для вызывающего это ничем не
            # отличается от обрыва транспорта: сессия узнаёт об этом тем же
            # путём (см. Session._recv_loop → on_disconnect), что и настоящий
            # разрыв WS.
            raise TransportError("пир покинул комнату")
        if not isinstance(msg, Relay):
            raise TransportError("ожидался RELAY-кадр")
        return msg.payload()

    async def close(self) -> None:
        self._closed = True
        await self._ws.close()
