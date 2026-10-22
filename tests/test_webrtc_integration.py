"""Два десктопа с aiortc: сессия апгрейдится с relay на прямой DataChannel."""

import asyncio
import hashlib
import os

import pytest

pytest.importorskip("aiortc")

from mys_decentralized import P2PService, RendezvousServer  # noqa: E402
from mys_decentralized.protocol import Role  # noqa: E402
from mys_decentralized.webrtc import WebRtcLink  # noqa: E402
from mys_storage import create_vault  # noqa: E402

FAST = {"time_cost": 1, "memory_cost": 8, "parallelism": 1}


async def _wait_for(pred, timeout: float = 20.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if pred():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("условие не выполнено за таймаут")


async def test_two_desktops_upgrade_to_direct_and_talk(tmp_path):
    server = RendezvousServer()
    host, port = await server.start("127.0.0.1", 0)
    url = f"ws://{host}:{port}/p2p"
    vaults = [create_vault(str(tmp_path / f"{n}.db"), b"pw", params=FAST) for n in "ab"]
    states: list[tuple[int, str]] = []
    services = [
        P2PService(v, url, connect_timeout=10, direct_factory=lambda: WebRtcLink([]),
                   on_state_change=lambda cid, st: states.append((cid, st)))
        for v in vaults
    ]
    for s in services:
        s.start()
    try:
        convs = await asyncio.gather(*(asyncio.to_thread(s.start_session, "прямой канал") for s in services))
        await _wait_for(lambda: all(s.is_direct(c) for s, c in zip(services, convs)))
        assert any(st == "direct" for _cid, st in states)

        a, b = services
        ca, cb = convs
        if a.role_of(ca) != Role.INITIATOR:
            a, b, ca, cb = b, a, cb, ca
        va = vaults[services.index(a)]
        vb = vaults[services.index(b)]
        await asyncio.to_thread(a.send, ca, "по прямому")
        await asyncio.to_thread(b.send, cb, "и обратно")
        data = os.urandom(300_000)  # несколько 64-КиБ чанков по DataChannel
        await asyncio.to_thread(a.send_file, ca, "f.bin", "application/octet-stream", data)

        def got(vault, conv, body):
            return any(m["direction"] == "in" and bytes(m["body"]) == body for m in vault.messages.list(conv))

        await _wait_for(lambda: got(vb, cb, "по прямому".encode()) and got(va, ca, "и обратно".encode()))
        await _wait_for(lambda: any(
            m["direction"] == "in" and m["kind"] == "file"
            and hashlib.sha256(bytes(m["body"])).digest() == hashlib.sha256(data).digest()
            for m in vb.messages.list(cb)
        ))
        assert a.is_direct(ca) and b.is_direct(cb)
    finally:
        for s in services:
            await asyncio.to_thread(s.stop)
        await server.stop()
