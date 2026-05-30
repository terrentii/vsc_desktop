"""Защищённая сессия: round-trip, персист/реконнект, битый/повторённый DATA."""

import asyncio

from mys_crypto import envelope
from mys_crypto.primitives import generate_x25519_keypair
from mys_crypto.ratchet import ratchet_init_alice, ratchet_init_bob
from mys_decentralized.protocol import Data, encode_message
from mys_decentralized.session import Session, open_session
from mys_decentralized.transport import InMemoryTransport, Transport
from mys_storage import create_vault

FAST = {"time_cost": 1, "memory_cost": 8, "parallelism": 1}


async def _wait_for(pred, timeout: float = 2.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if pred():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("условие не выполнено за таймаут")


def _two_vaults(tmp_path):
    av = create_vault(str(tmp_path / "alice.db"), b"pw-a", params=FAST)
    bv = create_vault(str(tmp_path / "bob.db"), b"pw-b", params=FAST)
    ca = av.conversations.add(mode="decentralized", room_id=b"room")
    cb = bv.conversations.add(mode="decentralized", room_id=b"room")
    return av, ca, bv, cb


def _seed_states(sk: bytes):
    bob_priv, bob_pub = generate_x25519_keypair()
    return ratchet_init_alice(sk, bob_pub), ratchet_init_bob(sk, (bob_priv, bob_pub))


class _Tee(Transport):
    """Транспорт-обёртка: записывает отправленные кадры (для теста replay)."""

    def __init__(self, inner: Transport):
        self._inner = inner
        self.sent: list[bytes] = []

    async def send(self, data: bytes) -> None:
        self.sent.append(data)
        await self._inner.send(data)

    async def recv(self) -> bytes:
        return await self._inner.recv()

    async def close(self) -> None:
        await self._inner.close()


async def test_session_roundtrip_preserves_order(tmp_path):
    av, ca, bv, cb = _two_vaults(tmp_path)
    sk = b"k" * 32
    a_state, b_state = _seed_states(sk)

    ta, tb = InMemoryTransport.connected_pair()
    got_b: list[bytes] = []
    got_a: list[bytes] = []
    sa = open_session(av, ca, ta, sk, a_state, on_message=got_a.append)
    sb = open_session(bv, cb, tb, sk, b_state, on_message=got_b.append)
    sa.start()
    sb.start()

    await sa.send("one")
    await sa.send("two")
    await _wait_for(lambda: got_b == [b"one", b"two"])

    await sb.send("ack")
    await _wait_for(lambda: got_a == [b"ack"])

    # Исходящие/входящие осели в обоих vault'ах.
    assert [m["direction"] for m in av.messages.list(ca)] == ["out", "out", "in"]
    assert [m["direction"] for m in bv.messages.list(cb)] == ["in", "in", "out"]

    await sa.close()
    await sb.close()


async def test_session_resumes_ratchet_after_reconnect(tmp_path):
    av, ca, bv, cb = _two_vaults(tmp_path)
    sk = b"k" * 32
    a_state, b_state = _seed_states(sk)

    ta, tb = InMemoryTransport.connected_pair()
    got_b: list[bytes] = []
    sa = open_session(av, ca, ta, sk, a_state)
    sb = open_session(bv, cb, tb, sk, b_state, on_message=got_b.append)
    sa.start()
    sb.start()
    await sa.send("before-reconnect")
    await _wait_for(lambda: got_b == [b"before-reconnect"])
    await sa.close()
    await sb.close()

    # Реконнект: новые транспорты, та же беседа. seed-состояния заведомо «битые» —
    # сессия обязана взять ratchet из vault, а не пересеять.
    ta2, tb2 = InMemoryTransport.connected_pair()
    bogus_a, bogus_b = _seed_states(b"x" * 32)
    got_b2: list[bytes] = []
    sa2 = open_session(av, ca, ta2, sk, bogus_a)
    sb2 = open_session(bv, cb, tb2, sk, bogus_b, on_message=got_b2.append)
    sa2.start()
    sb2.start()
    await sa2.send("after-reconnect")
    await _wait_for(lambda: got_b2 == [b"after-reconnect"])

    await sa2.close()
    await sb2.close()


async def test_corrupted_and_replayed_data_dropped(tmp_path):
    av, ca, bv, cb = _two_vaults(tmp_path)
    sk = b"k" * 32
    a_state, b_state = _seed_states(sk)

    ta_inner, tb = InMemoryTransport.connected_pair()
    ta = _Tee(ta_inner)
    got_b: list[bytes] = []
    sa = open_session(av, ca, ta, sk, a_state)
    sb = open_session(bv, cb, tb, sk, b_state, on_message=got_b.append)
    sa.start()
    sb.start()

    await sa.send("ok")
    await _wait_for(lambda: got_b == [b"ok"])

    # Битый sealed — отброшен, сессия жива.
    await ta_inner.send(encode_message(Data(b"too-short-garbage")))
    await asyncio.sleep(0.05)
    assert got_b == [b"ok"]

    # Replay уже доставленного DATA — отвергнут ratchet/AEAD.
    await ta_inner.send(ta.sent[-1])
    await asyncio.sleep(0.05)
    assert got_b == [b"ok"]

    # Канал по-прежнему рабочий.
    await sa.send("after")
    await _wait_for(lambda: got_b == [b"ok", b"after"])

    await sa.close()
    await sb.close()
