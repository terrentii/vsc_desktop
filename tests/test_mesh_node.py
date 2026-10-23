import asyncio
import os

import pytest

from mys_decentralized.errors import TransportError
from mys_decentralized.handshake import handshake
from mys_decentralized.protocol import Role
from mys_decentralized.transport import Transport
from mys_mesh import packet as P
from mys_mesh.link import Link
from mys_mesh.node import MeshClosed, MeshConfig, MeshNode, MeshRole
from mys_mesh.tags import tag_key
from mys_mesh.wire import MemoryWire, TcpWire

PRS = bytes(range(32))
KEY = tag_key(PRS)


def fast(**kw) -> MeshConfig:
    return MeshConfig(rreq_retry=0.2, sweep=0.2, **kw)


async def link(a: MeshNode, b: MeshNode) -> tuple[int, int]:
    wa, wb = MemoryWire.pair()
    return await asyncio.gather(a.attach(wa), b.attach(wb))


async def chain(n: int) -> list[MeshNode]:
    nodes = [MeshNode(fast()) for _ in range(n)]
    for x, y in zip(nodes, nodes[1:]):
        await link(x, y)
    return nodes


async def close_all(nodes):
    for n in nodes:
        await n.close()


class Adapter(Transport):
    """MeshTransport → Transport P2P-сессии (в этапе 2 — в P2PService)."""

    def __init__(self, t):
        self.t = t

    async def send(self, data):
        try:
            await self.t.send(data)
        except MeshClosed as e:
            raise TransportError(str(e)) from e

    async def recv(self):
        try:
            return await self.t.recv()
        except MeshClosed as e:
            raise TransportError(str(e)) from e

    async def close(self):
        await self.t.close()


async def test_chain_finds_and_handshakes():
    nodes = await chain(6)
    try:
        (ra, ta), (rb, tb) = await asyncio.gather(nodes[0].find(KEY, 10), nodes[-1].find(KEY, 10))
        assert {ra, rb} == {MeshRole.INITIATOR, MeshRole.RESPONDER}
        ha, hb = await asyncio.gather(handshake(Adapter(ta), PRS, Role(int(ra))),
                                      handshake(Adapter(tb), PRS, Role(int(rb))))
        assert ha.sk == hb.sk
        await ta.send(b"privet")
        assert await tb.recv() == b"privet"
        await tb.send(b"otvet")
        assert await ta.recv() == b"otvet"
        assert nodes[2].stats()["relayed_bytes"] > 0
    finally:
        await close_all(nodes)


async def test_grid_relays_each_rreq_once():
    nodes = [MeshNode(MeshConfig(rreq_retry=60, sweep=60)) for _ in range(9)]
    for i in range(9):
        if i % 3 < 2:
            await link(nodes[i], nodes[i + 1])
        if i < 6:
            await link(nodes[i], nodes[i + 3])
    try:
        with pytest.raises(TimeoutError):
            await nodes[0].find(KEY, 0.5)
        counts = [n.stats()["rreq_forwarded"] for n in nodes]
        assert counts[0] == 0 and all(c == 1 for c in counts[1:]), counts
    finally:
        await close_all(nodes)


async def test_reroute_after_break():
    a, b, c, d = (MeshNode(fast()) for _ in range(4))
    ab, _ = await link(a, b)
    ac, _ = await link(a, c)
    await link(b, d)
    await link(c, d)
    try:
        (_, ta), (_, td) = await asyncio.gather(a.find(KEY, 10), d.find(KEY, 10))
        await a.detach(ab if b.stats()["routes"] else ac)
        for t in (ta, td):
            with pytest.raises(MeshClosed):
                await asyncio.wait_for(t.recv(), 5)
        (_, ta), (_, td) = await asyncio.gather(a.find(KEY, 10), d.find(KEY, 10))
        await ta.send(b"x")
        assert await td.recv() == b"x"
    finally:
        await close_all([a, b, c, d])


async def test_simultaneous_search_makes_one_route():
    a, b = MeshNode(fast()), MeshNode(fast())
    await link(a, b)
    try:
        (ra, _), (rb, _) = await asyncio.gather(a.find(KEY, 5), b.find(KEY, 5))
        assert {ra, rb} == {MeshRole.INITIATOR, MeshRole.RESPONDER}
        await asyncio.sleep(0.5)
        assert a.stats()["routes"] == 1 and b.stats()["routes"] == 1
    finally:
        await close_all([a, b])


async def test_no_peer_times_out():
    nodes = await chain(3)
    try:
        with pytest.raises(TimeoutError):
            await nodes[0].find(KEY, 0.5)
    finally:
        await close_all(nodes)


async def test_flood_is_rate_limited():
    a, b = MeshNode(fast()), MeshNode(fast())
    await link(a, b)
    wa, wx = MemoryWire.pair()
    _, evil = await asyncio.gather(a.attach(wa), Link.open(wx))
    try:
        for _ in range(500):
            await evil.send(P.encode(P.Packet(P.RREQ, os.urandom(16), ttl=8,
                                              tag=os.urandom(32), nonce=os.urandom(16))))
        await asyncio.sleep(0.3)
        assert a.stats()["rreq_forwarded"] <= 15
        (ra, _), (rb, _) = await asyncio.gather(a.find(KEY, 5), b.find(KEY, 5))
        assert {ra, rb} == {MeshRole.INITIATOR, MeshRole.RESPONDER}
    finally:
        await close_all([a, b])


async def test_relay_off_blocks_transit_but_not_own():
    a, r, b = MeshNode(fast()), MeshNode(fast(relay=False)), MeshNode(fast())
    await link(a, r)
    await link(r, b)
    try:
        res = await asyncio.gather(a.find(KEY, 1), b.find(KEY, 1), return_exceptions=True)
        assert all(isinstance(x, TimeoutError) for x in res), res
        (x, _), (y, _) = await asyncio.gather(a.find(KEY, 5), r.find(KEY, 5))
        assert {x, y} == {MeshRole.INITIATOR, MeshRole.RESPONDER}
    finally:
        await close_all([a, r, b])


async def test_find_over_tcp():
    accepted = asyncio.get_running_loop().create_future()
    server = await asyncio.start_server(
        lambda r, w: accepted.set_result(TcpWire(r, w)), "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    a, b = MeshNode(fast()), MeshNode(fast())
    try:
        client = await TcpWire.connect("127.0.0.1", port)
        await asyncio.gather(a.attach(client), b.attach(await accepted))
        (_, ta), (_, tb) = await asyncio.gather(a.find(KEY, 5), b.find(KEY, 5))
        await ta.send(b"tcp")
        assert await tb.recv() == b"tcp"
    finally:
        await close_all([a, b])
        server.close()
