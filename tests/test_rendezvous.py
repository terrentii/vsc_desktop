"""Тестовый rendezvous-сервер: пейринг по room_id, роли, relay-ретрансляция."""

import asyncio

import pytest

from mys_decentralized.errors import PeerUnavailable
from mys_decentralized.protocol import Role
from mys_decentralized.rendezvous import RendezvousClient
from mys_decentralized.rendezvous_server import RendezvousServer
from mys_decentralized.transport import RelayTransport


async def _start_server() -> tuple[RendezvousServer, str, int]:
    server = RendezvousServer()
    host, port = await server.start("127.0.0.1", 0)
    return server, host, port


async def test_pairing_assigns_roles_and_exchanges_candidates():
    server, host, port = await _start_server()
    try:
        room = b"room-abc"
        c1, c2 = RendezvousClient(host, port), RendezvousClient(host, port)

        first = asyncio.create_task(c1.join(room, [("127.0.0.1", 1111)], timeout=2))
        await asyncio.sleep(0.05)  # первый ждёт пира
        r2 = await c2.join(room, [("127.0.0.1", 2222)], timeout=2)
        r1 = await first

        assert r1.role == Role.INITIATOR
        assert r2.role == Role.RESPONDER
        assert r1.peer_candidates == [("127.0.0.1", 2222)]
        assert r2.peer_candidates == [("127.0.0.1", 1111)]

        await r1.close()
        await r2.close()
    finally:
        await server.stop()


async def test_relay_forwards_opaque_payload_unchanged():
    server, host, port = await _start_server()
    try:
        room = b"room-relay"
        first = asyncio.create_task(
            RendezvousClient(host, port).join(room, [], timeout=2)
        )
        await asyncio.sleep(0.05)
        r2 = await RendezvousClient(host, port).join(room, [], timeout=2)
        r1 = await first

        t1, t2 = RelayTransport.from_rendezvous(r1), RelayTransport.from_rendezvous(r2)
        opaque = b"\x06\x00\x00\x00\x03abc"  # произвольные «непрозрачные» байты
        await t1.send(opaque)
        assert await t2.recv() == opaque
        # и в обратную сторону
        await t2.send(b"pong-bytes")
        assert await t1.recv() == b"pong-bytes"

        await r1.close()
        await r2.close()
    finally:
        await server.stop()


async def test_different_rooms_do_not_pair():
    server, host, port = await _start_server()
    try:
        with pytest.raises(PeerUnavailable):
            await asyncio.gather(
                RendezvousClient(host, port).join(b"room-1", [], timeout=0.3),
                RendezvousClient(host, port).join(b"room-2", [], timeout=0.3),
            )
    finally:
        await server.stop()


async def test_join_timeout_raises_peer_unavailable():
    server, host, port = await _start_server()
    try:
        with pytest.raises(PeerUnavailable):
            await RendezvousClient(host, port).join(b"lonely", [], timeout=0.2)
    finally:
        await server.stop()
