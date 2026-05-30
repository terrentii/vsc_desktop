"""Интеграция: два клиента через тестовый rendezvous обмениваются сообщениями.

Каждый клиент — свой ``P2PService`` (asyncio в фоновом потоке) и свой
зашифрованный vault. Rendezvous-сервер крутится на event loop теста; сервисы —
на своих loop'ах в отдельных потоках, общаются по реальным loopback TCP/UDP.
Блокирующие методы сервиса вызываются через ``asyncio.to_thread``, чтобы не
застопорить loop теста (на нём живёт сервер).
"""

import asyncio

import pytest

from mys_crypto.pake import cpace_msg  # noqa: F401  (косвенно через handshake)
from mys_decentralized import (
    P2PService,
    PAKEError,
    PeerUnavailable,
    RelayTransport,
    RendezvousClient,
    RendezvousServer,
    handshake,
)
from mys_decentralized.protocol import Role, derive_room_params
from mys_storage import create_vault

FAST = {"time_cost": 1, "memory_cost": 8, "parallelism": 1}


async def _start_server() -> tuple[RendezvousServer, str, int]:
    server = RendezvousServer()
    host, port = await server.start("127.0.0.1", 0)
    return server, host, port


async def _wait_for(pred, timeout: float = 5.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if pred():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("условие не выполнено за таймаут")


@pytest.mark.parametrize("allow_direct", [False, True], ids=["relay", "direct"])
async def test_two_clients_exchange_messages(tmp_path, allow_direct):
    server, host, port = await _start_server()
    av = create_vault(str(tmp_path / "a.db"), b"pw-a", params=FAST)
    bv = create_vault(str(tmp_path / "b.db"), b"pw-b", params=FAST)

    recv_a: list[bytes] = []
    recv_b: list[bytes] = []
    sa = P2PService(
        av, (host, port), allow_direct=allow_direct, connect_timeout=3,
        on_message=lambda _cid, body: recv_a.append(body),
    )
    sb = P2PService(
        bv, (host, port), allow_direct=allow_direct, connect_timeout=3,
        on_message=lambda _cid, body: recv_b.append(body),
    )
    sa.start()
    sb.start()
    try:
        phrase = "общая секретная фраза"
        conv_a, conv_b = await asyncio.gather(
            asyncio.to_thread(sa.start_session, phrase),
            asyncio.to_thread(sb.start_session, phrase),
        )

        # В Double Ratchet первым шлёт INITIATOR; RESPONDER отвечает после приёма.
        if sa.role_of(conv_a) == Role.INITIATOR:
            init, init_conv, init_recv = sa, conv_a, recv_a
            resp, resp_conv, resp_recv = sb, conv_b, recv_b
        else:
            init, init_conv, init_recv = sb, conv_b, recv_b
            resp, resp_conv, resp_recv = sa, conv_a, recv_a

        await asyncio.to_thread(init.send, init_conv, "привет")
        await _wait_for(lambda: resp_recv == ["привет".encode()])
        await asyncio.to_thread(resp.send, resp_conv, "и тебе")
        await _wait_for(lambda: init_recv == ["и тебе".encode()])

        # Данные осели в двух отдельных vault'ах.
        a_dirs = [m["direction"] for m in av.messages.list(conv_a)]
        b_dirs = [m["direction"] for m in bv.messages.list(conv_b)]
        assert "out" in a_dirs and "in" in a_dirs
        assert "out" in b_dirs and "in" in b_dirs
        # Сервер не видит фразу/открытый текст — беседа помечена непрозрачным room_id.
        assert av.conversations.get(conv_a)["room_id"] == derive_room_params(phrase)[0]
    finally:
        await asyncio.to_thread(sa.stop)
        await asyncio.to_thread(sb.stop)
        await server.stop()


async def test_peer_unavailable_when_alone(tmp_path):
    server, host, port = await _start_server()
    av = create_vault(str(tmp_path / "a.db"), b"pw", params=FAST)
    sa = P2PService(av, (host, port), connect_timeout=0.3)
    sa.start()
    try:
        with pytest.raises(PeerUnavailable):
            await asyncio.to_thread(sa.start_session, "никого больше нет")
    finally:
        await asyncio.to_thread(sa.stop)
        await server.stop()


async def test_different_phrases_do_not_connect(tmp_path):
    """Разные фразы ⇒ разные room_id ⇒ клиенты не парятся (peer unavailable)."""
    server, host, port = await _start_server()
    av = create_vault(str(tmp_path / "a.db"), b"pw-a", params=FAST)
    bv = create_vault(str(tmp_path / "b.db"), b"pw-b", params=FAST)
    sa = P2PService(av, (host, port), connect_timeout=0.4)
    sb = P2PService(bv, (host, port), connect_timeout=0.4)
    sa.start()
    sb.start()
    try:
        results = await asyncio.gather(
            asyncio.to_thread(sa.start_session, "фраза один"),
            asyncio.to_thread(sb.start_session, "фраза два"),
            return_exceptions=True,
        )
        assert all(isinstance(r, PeerUnavailable) for r in results)
    finally:
        await asyncio.to_thread(sa.stop)
        await asyncio.to_thread(sb.stop)
        await server.stop()


async def test_mitm_in_room_without_phrase_fails_pake(tmp_path):
    """Атакующий входит в правильную комнату, но без фразы ⇒ honest видит PAKEError."""
    server, host, port = await _start_server()
    av = create_vault(str(tmp_path / "a.db"), b"pw", params=FAST)
    errors: list[Exception] = []
    sa = P2PService(
        av, (host, port), allow_direct=False, connect_timeout=3,
        on_error=lambda _cid, exc: errors.append(exc),
    )
    sa.start()

    phrase = "только honest знает фразу"
    room_id, _prs = derive_room_params(phrase)

    async def attacker() -> None:
        rv = await RendezvousClient(host, port).join(room_id, [], timeout=3)
        transport = RelayTransport.from_rendezvous(rv)
        try:
            await handshake(transport, b"attacker-wrong-prs", rv.role)
        except PAKEError:
            pass  # ожидаемо: атакующий тоже не сойдётся
        finally:
            await rv.close()

    att = asyncio.create_task(attacker())
    try:
        with pytest.raises(PAKEError):
            await asyncio.to_thread(sa.start_session, phrase)
        await att
        assert any(isinstance(e, PAKEError) for e in errors)
    finally:
        await asyncio.to_thread(sa.stop)
        await server.stop()
