"""Транспорты: relay через rendezvous и in-memory."""

import asyncio

import pytest

from mys_decentralized.errors import TransportError
from mys_decentralized.protocol import PeerLeft, Relay, encode_message
from mys_decentralized.transport import (
    InMemoryTransport,
    RelayTransport,
    Transport,
)


class _FakeWS:
    """Двойник websockets-соединения: recv() отдаёт кадры из очереди по одному."""

    def __init__(self, frames: list[bytes]):
        self._frames = list(frames)
        self.closed = False

    async def recv(self) -> bytes:
        return self._frames.pop(0)

    async def send(self, data: bytes) -> None:
        pass

    async def close(self) -> None:
        self.closed = True


async def test_relay_transport_recv_returns_relay_payload():
    ws = _FakeWS([encode_message(Relay(payload=b"hi"))])
    rt = RelayTransport(ws)
    assert await rt.recv() == b"hi"


async def test_relay_transport_recv_raises_on_peer_left():
    """PEER_LEFT — сигнал сервера «пир ушёл», не RELAY-кадр: для вызывающего
    (Session._recv_loop) это должно выглядеть как обрыв транспорта, чтобы
    сработал тот же путь оповещения об офлайне, что и при реальном разрыве WS."""
    ws = _FakeWS([encode_message(PeerLeft())])
    rt = RelayTransport(ws)
    with pytest.raises(TransportError):
        await rt.recv()


async def test_inmemory_roundtrip_and_close():
    a, b = InMemoryTransport.connected_pair()
    await a.send(b"hello")
    assert await b.recv() == b"hello"
    await a.close()
    with pytest.raises(TransportError):
        await b.recv()
