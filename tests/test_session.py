"""Защищённая сессия: round-trip, персист/реконнект, битый/повторённый DATA."""

import asyncio
import hashlib

import pytest

from mys_crypto import envelope
from mys_crypto.primitives import generate_x25519_keypair
from mys_crypto.ratchet import ratchet_init_alice, ratchet_init_bob
from mys_decentralized import filetransfer as ft
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


async def test_responder_queues_outgoing_until_primed(tmp_path):
    """RESPONDER (cks=None) не может слать первым: исходящее ждёт в очереди как
    pending и уходит, как только INITIATOR пришлёт prime."""
    av, ca, bv, cb = _two_vaults(tmp_path)
    sk = b"k" * 32
    a_state, b_state = _seed_states(sk)

    ta, tb = InMemoryTransport.connected_pair()
    got_a: list[bytes] = []
    sa = open_session(av, ca, ta, sk, a_state, on_message=got_a.append)  # INITIATOR
    sb = open_session(bv, cb, tb, sk, b_state)                           # RESPONDER
    sa.start()
    sb.start()

    # Bob ещё не может слать.
    assert sb.can_send is False
    await sb.send("from-bob")  # → очередь, запись pending
    await asyncio.sleep(0.05)
    assert [(m["direction"], m["status"]) for m in bv.messages.list(cb)] == [("out", "pending")]
    assert got_a == []  # Alice ничего не получила

    # Alice праймит → Bob открывает отправляющую цепочку и флашит очередь.
    await sa.send_prime()
    await _wait_for(lambda: got_a == [b"from-bob"])
    assert sb.can_send is True
    assert [(m["direction"], m["status"]) for m in bv.messages.list(cb)] == [("out", "sent")]
    # prime не сохранён как сообщение ни у кого — у Alice только входящее от Bob.
    assert [m["direction"] for m in av.messages.list(ca)] == ["in"]

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


# --- передача файлов -----------------------------------------------------------

async def test_session_send_file_roundtrip_reassembles(tmp_path, monkeypatch):
    monkeypatch.setattr(ft, "CHUNK_SIZE", 16)  # маленькие чанки для скорости теста
    av, ca, bv, cb = _two_vaults(tmp_path)
    sk = b"k" * 32
    a_state, b_state = _seed_states(sk)

    ta, tb = InMemoryTransport.connected_pair()
    got_b: list[bytes] = []
    sa = open_session(av, ca, ta, sk, a_state)
    sb = open_session(bv, cb, tb, sk, b_state, on_message=got_b.append)
    sa.start()
    sb.start()

    # Alice — INITIATOR, может слать сразу.
    data = bytes(range(256)) * 3  # 768 байт -> 48 чанков по 16 байт
    await sa.send_file("report.txt", "text/plain", data)
    await _wait_for(lambda: got_b == [data])

    rows = bv.messages.list(cb)
    assert len(rows) == 1
    assert rows[0]["kind"] == "file"
    assert rows[0]["filename"] == "report.txt"
    assert rows[0]["mime_type"] == "text/plain"
    assert rows[0]["body"] == data
    assert rows[0]["direction"] == "in"

    await sa.close()
    await sb.close()


async def test_session_send_file_out_of_order_chunks_reassemble(tmp_path, monkeypatch):
    monkeypatch.setattr(ft, "CHUNK_SIZE", 8)
    av, ca, bv, cb = _two_vaults(tmp_path)
    sk = b"k" * 32
    a_state, b_state = _seed_states(sk)

    ta, tb = InMemoryTransport.connected_pair()
    got_b: list[bytes] = []
    sa = open_session(av, ca, ta, sk, a_state)
    sb = open_session(bv, cb, tb, sk, b_state, on_message=got_b.append)
    sa.start()
    sb.start()

    data = b"0123456789abcdef" * 2  # 32 байта -> 4 чанка по 8 байт
    async with sa._lock:
        chunks = ft.split_chunks(data)
        meta = ft.FileMeta(
            transfer_id=b"z" * ft.TRANSFER_ID_LEN, total_size=len(data),
            chunk_size=ft.CHUNK_SIZE, chunk_count=len(chunks),
            sha256=hashlib.sha256(data).digest(), mime_type="application/octet-stream",
            filename="blob.bin",
        )
        # Отправляем чанки в обратном порядке, затем META последней.
        for idx in reversed(range(len(chunks))):
            fc = ft.FileChunk(transfer_id=meta.transfer_id, index=idx, data=chunks[idx])
            payload = bytes([ft.KIND_FILE_CHUNK]) + ft.encode_file_chunk(fc)
            await sa._seal_and_send(payload)
        meta_payload = bytes([ft.KIND_FILE_META]) + ft.encode_file_meta(meta)
        await sa._seal_and_send(meta_payload)
        sa._vault.ratchet.save_state(sa._conv, sa._state)

    await _wait_for(lambda: got_b == [data])
    rows = bv.messages.list(cb)
    assert rows[0]["kind"] == "file" and rows[0]["body"] == data

    await sa.close()
    await sb.close()


async def test_session_send_file_bad_checksum_dropped(tmp_path, monkeypatch):
    monkeypatch.setattr(ft, "CHUNK_SIZE", 8)
    av, ca, bv, cb = _two_vaults(tmp_path)
    sk = b"k" * 32
    a_state, b_state = _seed_states(sk)

    ta, tb = InMemoryTransport.connected_pair()
    got_b: list[bytes] = []
    sa = open_session(av, ca, ta, sk, a_state)
    sb = open_session(bv, cb, tb, sk, b_state, on_message=got_b.append)
    sa.start()
    sb.start()

    data = b"corrupted-data!!"
    async with sa._lock:
        chunks = ft.split_chunks(data)
        meta = ft.FileMeta(
            transfer_id=b"y" * ft.TRANSFER_ID_LEN, total_size=len(data),
            chunk_size=ft.CHUNK_SIZE, chunk_count=len(chunks),
            sha256=b"\x00" * 32,  # заведомо неверная контрольная сумма
            mime_type="application/octet-stream", filename="bad.bin",
        )
        meta_payload = bytes([ft.KIND_FILE_META]) + ft.encode_file_meta(meta)
        await sa._seal_and_send(meta_payload)
        for idx, chunk in enumerate(chunks):
            fc = ft.FileChunk(transfer_id=meta.transfer_id, index=idx, data=chunk)
            payload = bytes([ft.KIND_FILE_CHUNK]) + ft.encode_file_chunk(fc)
            await sa._seal_and_send(payload)
        sa._vault.ratchet.save_state(sa._conv, sa._state)

    await asyncio.sleep(0.05)
    assert got_b == []
    assert bv.messages.list(cb) == []

    # Сессия по-прежнему жива.
    await sa.send("still-alive")
    await _wait_for(lambda: got_b == [b"still-alive"])

    await sa.close()
    await sb.close()


async def test_send_file_raises_when_not_primed(tmp_path):
    av, ca, bv, cb = _two_vaults(tmp_path)
    sk = b"k" * 32
    a_state, b_state = _seed_states(sk)

    ta, tb = InMemoryTransport.connected_pair()
    sa = open_session(av, ca, ta, sk, a_state)  # INITIATOR
    sb = open_session(bv, cb, tb, sk, b_state)  # RESPONDER
    sa.start()
    sb.start()

    assert sb.can_send is False
    with pytest.raises(RuntimeError):
        await sb.send_file("x.txt", "text/plain", b"data")
    assert bv.messages.list(cb) == []

    await sa.close()
    await sb.close()


async def test_send_file_rejects_oversized(tmp_path, monkeypatch):
    monkeypatch.setattr(ft, "MAX_FILE_SIZE", 10)
    av, ca, bv, cb = _two_vaults(tmp_path)
    sk = b"k" * 32
    a_state, b_state = _seed_states(sk)

    ta, tb = InMemoryTransport.connected_pair()
    sa = open_session(av, ca, ta, sk, a_state)
    sb = open_session(bv, cb, tb, sk, b_state)
    sa.start()
    sb.start()

    with pytest.raises(ValueError):
        await sa.send_file("big.bin", "application/octet-stream", b"x" * 11)
    assert av.messages.list(ca) == []

    await sa.close()
    await sb.close()


async def test_close_clears_pending_files(tmp_path, monkeypatch):
    monkeypatch.setattr(ft, "CHUNK_SIZE", 8)
    av, ca, bv, cb = _two_vaults(tmp_path)
    sk = b"k" * 32
    a_state, b_state = _seed_states(sk)

    ta, tb = InMemoryTransport.connected_pair()
    sa = open_session(av, ca, ta, sk, a_state)
    sb = open_session(bv, cb, tb, sk, b_state)
    sa.start()
    sb.start()

    data = b"0123456789abcdef"
    async with sa._lock:
        chunks = ft.split_chunks(data)
        assert len(chunks) == 2
        meta = ft.FileMeta(
            transfer_id=b"w" * ft.TRANSFER_ID_LEN, total_size=len(data),
            chunk_size=ft.CHUNK_SIZE, chunk_count=len(chunks),
            sha256=b"0" * 32, mime_type="x", filename="f",
        )
        meta_payload = bytes([ft.KIND_FILE_META]) + ft.encode_file_meta(meta)
        await sa._seal_and_send(meta_payload)
        # Только первый чанк — трансфер остаётся незавершённым у Bob.
        fc = ft.FileChunk(transfer_id=meta.transfer_id, index=0, data=chunks[0])
        payload = bytes([ft.KIND_FILE_CHUNK]) + ft.encode_file_chunk(fc)
        await sa._seal_and_send(payload)
        sa._vault.ratchet.save_state(sa._conv, sa._state)

    await asyncio.sleep(0.05)
    assert sb._pending_files != {}
    await sb.close()
    assert sb._pending_files == {}

    await sa.close()
