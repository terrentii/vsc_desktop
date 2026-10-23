import asyncio

import pytest

from mys_mesh.link import Link
from mys_mesh.packet import MeshProtocolError
from mys_mesh.wire import MAX_FRAME, MemoryWire, TcpWire, WireClosed


async def _links(wa, wb):
    return await asyncio.gather(Link.open(wa), Link.open(wb))


async def test_handshake_and_exchange():
    la, lb = await _links(*MemoryWire.pair())
    await la.send(b"ping")
    await lb.send(b"pong")
    assert await lb.recv() == b"ping"
    assert await la.recv() == b"pong"


async def test_garbage_frame_breaks_link():
    wa, wb = MemoryWire.pair()
    la, lb = await _links(wa, wb)
    await wa.send(b"x" * 40)
    with pytest.raises(MeshProtocolError):
        await lb.recv()


async def test_bad_magic_rejected():
    wa, wb = MemoryWire.pair()
    opening = asyncio.create_task(Link.open(wb))
    await wa.send(b"XXXX\x01" + bytes(32))
    with pytest.raises(MeshProtocolError):
        await opening


async def test_oversize_frame_closes_wire():
    wa, wb = MemoryWire.pair()
    await wa.send(bytes(MAX_FRAME + 1))
    with pytest.raises(WireClosed):
        await wb.recv()


async def test_close_reaches_both_sides():
    wa, wb = MemoryWire.pair()
    await wa.close()
    for w in (wa, wb):
        with pytest.raises(WireClosed):
            await w.recv()


async def test_tcp_wire_link():
    accepted = asyncio.get_running_loop().create_future()
    server = await asyncio.start_server(
        lambda r, w: accepted.set_result(TcpWire(r, w)), "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    client = await TcpWire.connect("127.0.0.1", port)
    la, lb = await _links(client, await accepted)
    await la.send(b"tcp")
    assert await lb.recv() == b"tcp"
    await la.close()
    with pytest.raises(WireClosed):
        await lb.recv()
    server.close()
