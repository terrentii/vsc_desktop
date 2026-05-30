"""Транспорт: доставка непрозрачных кадров пиру.

Граница CLAUDE.md: транспорт ничего не знает о шифровании — он переносит
непрозрачные ``bytes`` (готовые wire-сообщения из :mod:`.protocol`) от одного
пира к другому. Слои ``handshake``/``session`` кладут поверх CPace/ratchet/AEAD.

Здесь: ABC ``Transport``, in-memory дуплекс для тестов, ``RelayTransport``
(relay-first путь через rendezvous-сервер по WebSocket) и ``DirectTransport``
(UDP hole-punch, каркас) с выбором пути ``establish_transport`` (direct →
fallback на relay).

Транспорт rendezvous/relay — WebSocket (один порт с веб-сервером, WSS/прокси-
дружелюбно): каждый wire-кадр :mod:`.protocol` отправляется как одно бинарное
WS-сообщение (границы сообщений сохраняет сам WebSocket).
"""

import asyncio
from abc import ABC, abstractmethod

from websockets.exceptions import ConnectionClosed

from .errors import TransportError
from .protocol import (
    Punch,
    PunchAck,
    Relay,
    decode_message,
    encode_message,
)

_PUNCH_TYPES = frozenset({int(Punch.TYPE), int(PunchAck.TYPE)})


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
        if not isinstance(msg, Relay):
            raise TransportError("ожидался RELAY-кадр")
        return msg.payload()

    async def close(self) -> None:
        self._closed = True
        await self._ws.close()


# --- прямой путь: UDP hole-punch (каркас) ------------------------------------

class _UDPProto(asyncio.DatagramProtocol):
    """Складывает входящие датаграммы в очередь ``(data, addr)``."""

    def __init__(self) -> None:
        self.queue: asyncio.Queue = asyncio.Queue()

    def datagram_received(self, data: bytes, addr) -> None:
        self.queue.put_nowait((data, addr))

    def error_received(self, exc) -> None:  # ICMP «порт недоступен» и т.п.
        pass


async def open_udp_endpoint(
    local_host: str = "127.0.0.1", local_port: int = 0
) -> tuple[asyncio.DatagramTransport, _UDPProto, tuple[str, int]]:
    """Открыть UDP-эндпоинт; вернуть ``(udp, proto, sockname)``.

    Адрес ``sockname`` — кандидат, который анонсируется в ``HELLO`` до hole-punch.
    """
    loop = asyncio.get_running_loop()
    udp, proto = await loop.create_datagram_endpoint(
        _UDPProto, local_addr=(local_host, local_port)
    )
    sock = udp.get_extra_info("sockname")
    return udp, proto, (sock[0], sock[1])


async def _hole_punch(
    udp: asyncio.DatagramTransport,
    proto: _UDPProto,
    peer_candidates: list[tuple[str, int]],
    timeout: float,
) -> tuple[str, int]:
    """Симметричный hole-punch: слать ``PUNCH`` всем кандидатам, ждать встречный
    ``PUNCH``/``PUNCH_ACK``. Возвращает подтверждённый адрес пира или бросает
    :class:`TransportError` по таймауту."""
    loop = asyncio.get_running_loop()
    punch = encode_message(Punch())
    ack = encode_message(PunchAck())
    deadline = loop.time() + timeout
    confirmed: tuple[str, int] | None = None

    while confirmed is None and loop.time() < deadline:
        for cand in peer_candidates:
            udp.sendto(punch, cand)
        try:
            data, addr = await asyncio.wait_for(proto.queue.get(), 0.05)
        except asyncio.TimeoutError:
            continue
        if not data:
            continue
        if data[0] == int(Punch.TYPE):
            udp.sendto(ack, addr)  # подтвердить встречную пробу
            confirmed = addr
        elif data[0] == int(PunchAck.TYPE):
            confirmed = addr

    if confirmed is None:
        raise TransportError("hole-punch не удался (нет ответа пира)")
    udp.sendto(ack, confirmed)  # финальный ACK на случай гонки
    return confirmed


class DirectTransport(Transport):
    """Прямой UDP-канал к пиру после успешного hole-punch (один кадр = датаграмма).

    Каркас: кандидаты — локальные адреса (loopback/LAN), без живого STUN. Поздние
    ``PUNCH``/``PUNCH_ACK`` отфильтровываются на приёме."""

    def __init__(
        self,
        udp: asyncio.DatagramTransport,
        proto: _UDPProto,
        peer_addr: tuple[str, int],
    ):
        self._udp = udp
        self._proto = proto
        self._peer = peer_addr
        self._closed = False

    @property
    def peer_addr(self) -> tuple[str, int]:
        return self._peer

    @classmethod
    async def establish(
        cls,
        udp: asyncio.DatagramTransport,
        proto: _UDPProto,
        peer_candidates: list[tuple[str, int]],
        timeout: float = 1.0,
    ) -> "DirectTransport":
        peer = await _hole_punch(udp, proto, peer_candidates, timeout)
        return cls(udp, proto, peer)

    async def send(self, data: bytes) -> None:
        if self._closed:
            raise TransportError("send в закрытый direct-транспорт")
        self._udp.sendto(data, self._peer)

    async def recv(self) -> bytes:
        while True:
            if self._closed:
                raise TransportError("direct-транспорт закрыт")
            data, _addr = await self._proto.queue.get()
            if data and data[0] in _PUNCH_TYPES:
                continue  # хвост hole-punch — не данные сессии
            return data

    async def close(self) -> None:
        self._closed = True
        self._udp.close()


async def establish_transport(
    udp: asyncio.DatagramTransport,
    proto: _UDPProto,
    peer_candidates: list[tuple[str, int]],
    relay_factory,
    *,
    punch_timeout: float = 1.0,
) -> Transport:
    """Выбор пути: пробуем прямой UDP (hole-punch), при неудаче — relay.

    ``udp``/``proto`` — заранее открытый эндпоинт (его адрес уже анонсирован в
    ``HELLO``). ``relay_factory`` — корутина, строящая ``RelayTransport`` поверх
    rendezvous-соединения; вызывается только при провале hole-punch.
    """
    try:
        return await DirectTransport.establish(
            udp, proto, peer_candidates, punch_timeout
        )
    except TransportError:
        udp.close()
        return await relay_factory()
