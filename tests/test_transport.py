"""Транспорт: DirectTransport (hole-punch на loopback) и fallback на relay."""

import asyncio

import pytest

from mys_decentralized.errors import TransportError
from mys_decentralized.protocol import PeerLeft, Relay, encode_message
from mys_decentralized.transport import (
    DirectTransport,
    InMemoryTransport,
    RelayTransport,
    Transport,
    establish_transport,
    open_udp_endpoint,
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


async def test_direct_transport_loopback_hole_punch():
    udp_a, proto_a, addr_a = await open_udp_endpoint()
    udp_b, proto_b, addr_b = await open_udp_endpoint()

    ta, tb = await asyncio.gather(
        DirectTransport.establish(udp_a, proto_a, [addr_b], timeout=2),
        DirectTransport.establish(udp_b, proto_b, [addr_a], timeout=2),
    )
    try:
        await ta.send(b"ping")
        assert await tb.recv() == b"ping"
        await tb.send(b"pong")
        assert await ta.recv() == b"pong"
    finally:
        await ta.close()
        await tb.close()


async def test_establish_transport_falls_back_to_relay_without_ack():
    udp, proto, _addr = await open_udp_endpoint()
    relay = InMemoryTransport.connected_pair()[0]
    used_relay = False

    async def relay_factory() -> Transport:
        nonlocal used_relay
        used_relay = True
        return relay

    # Пир по порту 1 не ответит ⇒ hole-punch истечёт ⇒ откат на relay.
    result = await establish_transport(
        udp, proto, [("127.0.0.1", 1)], relay_factory, punch_timeout=0.25
    )
    assert used_relay is True
    assert result is relay


async def test_establish_transport_prefers_direct_when_punch_succeeds():
    udp_a, proto_a, addr_a = await open_udp_endpoint()
    udp_b, proto_b, addr_b = await open_udp_endpoint()

    async def never_relay() -> Transport:  # pragma: no cover
        raise AssertionError("relay не должен использоваться при успехе hole-punch")

    ta, tb = await asyncio.gather(
        establish_transport(udp_a, proto_a, [addr_b], never_relay, punch_timeout=2),
        establish_transport(udp_b, proto_b, [addr_a], never_relay, punch_timeout=2),
    )
    try:
        assert isinstance(ta, DirectTransport)
        await ta.send(b"direct")
        assert await tb.recv() == b"direct"
    finally:
        await ta.close()
        await tb.close()
