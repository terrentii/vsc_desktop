"""Mesh, этап 2: PEERS, WebSocket-провод, интернет-связь через публичный узел."""

import asyncio

import pytest
from websockets.asyncio.server import serve

from mys_mesh import packet as P
from mys_mesh.internet import MeshInternet
from mys_mesh.node import MeshConfig, MeshNode, MeshRole
from mys_mesh.tags import tag_key
from mys_mesh.wire import MemoryWire, WsWire

KEY = tag_key(bytes(range(32)))


def fast(**kw):
    return MeshConfig(rreq_retry=0.2, sweep=0.2, **kw)


def test_peers_roundtrip_and_validation():
    body = P.encode_peers(["wss://a.ru/mesh", "ws://127.0.0.1:5/mesh", "http://bad", "wss://x y"])
    assert P.decode_peers(body) == ["wss://a.ru/mesh", "ws://127.0.0.1:5/mesh"]
    p = P.Packet(P.PEERS, bytes(16), payload=body)
    assert P.decode(P.encode(p)) == p
    for bad in (b"ftp://x", b"wss://" + b"a" * 300, b"\n".join([b"wss://a"] * 17)):
        with pytest.raises(P.MeshProtocolError):
            P.decode(bytes([1, P.PEERS, 0, 0]) + bytes(16) + bad)


async def test_public_node_shares_its_url():
    hub = MeshNode(fast(public_url="wss://hub.example/mesh"))
    client = MeshNode(fast())
    learned = []
    client.on_peers = learned.extend
    wa, wb = MemoryWire.pair()
    try:
        await asyncio.gather(hub.attach(wa), client.attach(wb))
        for _ in range(50):
            if learned:
                break
            await asyncio.sleep(0.02)
        assert learned == ["wss://hub.example/mesh"] and client.known_urls == learned
    finally:
        await hub.close()
        await client.close()


async def test_two_clients_meet_through_websocket_hub():
    hub = MeshNode(fast())

    async def handler(conn):
        await hub.serve(WsWire(conn))

    async with serve(handler, "127.0.0.1", 0, max_size=None) as server:
        url = f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}"
        a, b = MeshNode(fast()), MeshNode(fast())
        ia = MeshInternet(a, lambda: [url], tick=0.05)
        ib = MeshInternet(b, lambda: [url], tick=0.05)
        ia.start()
        ib.start()
        try:
            (ra, ta), (rb, tb) = await asyncio.gather(a.find(KEY, 10), b.find(KEY, 10))
            assert {ra, rb} == {MeshRole.INITIATOR, MeshRole.RESPONDER}
            await ta.send(b"through hub")
            assert await tb.recv() == b"through hub"
            assert ia.connected() == [url] and hub.stats()["relayed_bytes"] > 0
        finally:
            await ia.stop()
            await ib.stop()
            for n in (a, b, hub):
                await n.close()


async def test_internet_retries_unreachable_with_backoff():
    node = MeshNode(fast())
    calls = []

    async def failing(url):
        calls.append(url)
        raise OSError("нет сети")

    net = MeshInternet(node, lambda: ["wss://down.example/mesh"], connect=failing, tick=0.01)
    net.start()
    await asyncio.sleep(0.3)
    await net.stop()
    await node.close()
    assert len(calls) == 1  # следующая попытка — не раньше чем через 2 с
