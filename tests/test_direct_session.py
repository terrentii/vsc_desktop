"""Сессия с relay и прямым транспортом (WebRTC подменён in-memory парой)."""

import asyncio

from mys_crypto.primitives import generate_x25519_keypair
from mys_crypto.ratchet import ratchet_init_alice, ratchet_init_bob
from mys_decentralized.session import open_session
from mys_decentralized.transport import InMemoryTransport, Transport
from mys_storage import create_vault

FAST = {"time_cost": 1, "memory_cost": 8, "parallelism": 1}


async def _wait_for(pred, timeout: float = 3.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if pred():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("условие не выполнено за таймаут")


class _Counting(Transport):
    def __init__(self, inner):
        self.inner, self.sent = inner, 0

    async def send(self, data):
        self.sent += 1
        await self.inner.send(data)

    async def recv(self):
        return await self.inner.recv()

    async def close(self):
        await self.inner.close()


class _Side:
    def __init__(self, vault, conv, relay):
        self.vault, self.conv, self.relay = vault, conv, relay
        self.signals: list[str] = []
        self.disconnected = False
        self.direct_closed = 0
        self.session = None

    def incoming(self):
        return [m["body"] for m in self.vault.messages.list(self.conv) if m["direction"] == "in"]


async def _pair(tmp_path):
    sk = b"k" * 32
    bob_priv, bob_pub = generate_x25519_keypair()
    states = [ratchet_init_alice(sk, bob_pub), ratchet_init_bob(sk, (bob_priv, bob_pub))]
    ta, tb = InMemoryTransport.connected_pair()
    sides = []
    for name, t, st in (("a", ta, states[0]), ("b", tb, states[1])):
        v = create_vault(str(tmp_path / f"{name}.db"), b"pw", params=FAST)
        conv = v.conversations.add(mode="decentralized", room_id=b"room")
        side = _Side(v, conv, _Counting(t))
        side.session = open_session(
            v, conv, side.relay, sk, st,
            on_disconnect=lambda s=side: setattr(s, "disconnected", True),
            on_signal=side.signals.append,
            on_direct_closed=lambda s=side: setattr(s, "direct_closed", s.direct_closed + 1),
        )
        side.session.start()
        sides.append(side)
    a, b = sides
    await a.session.send_prime()
    await _wait_for(lambda: b.session.can_send)
    return a, b


def _attach(a, b):
    da, db = InMemoryTransport.connected_pair()
    a.session.attach_direct(da)
    b.session.attach_direct(db)
    return da, db


async def test_sends_go_direct_once_attached(tmp_path):
    a, b = await _pair(tmp_path)
    _attach(a, b)
    assert a.session.is_direct
    before = a.relay.sent
    await a.session.send("по прямому")
    await b.session.send("и обратно")
    await _wait_for(lambda: b.incoming() == ["по прямому".encode()] and a.incoming() == ["и обратно".encode()])
    assert a.relay.sent == before


async def test_direct_drop_falls_back_to_relay(tmp_path):
    a, b = await _pair(tmp_path)
    _da, db = _attach(a, b)
    await db.close()
    await _wait_for(lambda: not a.session.is_direct and a.direct_closed == 1)
    await a.session.send("через сервер")
    await _wait_for(lambda: b.incoming() == ["через сервер".encode()])
    assert not a.disconnected and not b.disconnected


async def test_signals_reach_callback_not_stored(tmp_path):
    a, b = await _pair(tmp_path)
    await a.session.send_signal('{"t":"offer","sdp":"v=0"}')
    await _wait_for(lambda: b.signals == ['{"t":"offer","sdp":"v=0"}'])
    assert b.vault.messages.list(b.conv) == []


async def test_signal_goes_via_relay_even_when_direct_attached(tmp_path):
    a, b = await _pair(tmp_path)
    _x, other = InMemoryTransport.connected_pair()
    b.session.attach_direct(other)  # у b прямой есть, у a — ещё нет
    await b.session.send_signal('{"t":"answer"}')
    await _wait_for(lambda: a.signals == ['{"t":"answer"}'])


async def test_relay_loss_keeps_session_while_direct_alive(tmp_path):
    a, b = await _pair(tmp_path)
    da, _db = _attach(a, b)
    await a.relay.close()
    await asyncio.sleep(0.2)
    assert not b.disconnected
    await a.session.send("живой по прямому")
    await _wait_for(lambda: b.incoming() == ["живой по прямому".encode()])
    await da.close()
    await _wait_for(lambda: b.disconnected)
