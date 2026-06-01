"""Проводка P2P в GUI: боевая фабрика + интеграция двух контроллеров."""

import asyncio

import pytest

from mys_decentralized import P2PService, RendezvousServer
from mys_decentralized.protocol import Role
from mys_storage import create_vault
from mys_ui.app import _p2p_factory
from mys_ui.controller import AppController, DECENTRALIZED

FAST = {"time_cost": 1, "memory_cost": 8, "parallelism": 1}


def test_p2p_factory_builds_service(tmp_path):
    vault = create_vault(str(tmp_path / "v.db"), b"pw", params=FAST)
    svc = _p2p_factory(
        vault,
        "ws://127.0.0.1:1/p2p",
        on_message=None,
        on_state_change=None,
        on_error=None,
    )
    assert isinstance(svc, P2PService)


# ---------------------------------------------------------------------------
# Вспомогательные функции для интеграционного теста
# ---------------------------------------------------------------------------

async def _start_server() -> tuple[RendezvousServer, str]:
    server = RendezvousServer()
    host, port = await server.start("127.0.0.1", 0)
    return server, f"ws://{host}:{port}/p2p"


async def _wait_for(pred, timeout: float = 5.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if pred():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("условие не выполнено за таймаут")


def _test_factory(vault, rendezvous_url, *, on_message, on_state_change, on_error):
    # Тестовая фабрика: без прямого hole-punch, короткий таймаут коннекта.
    return P2PService(
        vault,
        rendezvous_url,
        allow_direct=False,
        connect_timeout=3,
        on_message=on_message,
        on_state_change=on_state_change,
        on_error=on_error,
    )


async def test_two_controllers_exchange_message(tmp_path):
    """Два AppController через встроенный rendezvous: проводка фабрика→ensure→
    start_session→on_message, обмен одним сообщением от INITIATOR к RESPONDER."""
    server, url = await _start_server()
    recv_a: list[bytes] = []
    recv_b: list[bytes] = []

    ca = AppController(str(tmp_path / "a.db"), kdf_params=FAST, p2p_factory=_test_factory)
    cb = AppController(str(tmp_path / "b.db"), kdf_params=FAST, p2p_factory=_test_factory)
    ca.create_vault(b"pw-a")
    cb.create_vault(b"pw-b")
    ca.set_mode(DECENTRALIZED)
    cb.set_mode(DECENTRALIZED)
    ca.add_p2p_observer(
        on_message=lambda cid, body: recv_a.append(body),
        on_state_change=None,
        on_error=None,
    )
    cb.add_p2p_observer(
        on_message=lambda cid, body: recv_b.append(body),
        on_state_change=None,
        on_error=None,
    )
    try:
        phrase = "общая фраза для проводки gui"
        conv_a, conv_b = await asyncio.gather(
            asyncio.to_thread(
                ca.create_conversation, phrase, room_phrase=phrase, rendezvous_url=url
            ),
            asyncio.to_thread(
                cb.create_conversation, phrase, room_phrase=phrase, rendezvous_url=url
            ),
        )
        # Первым в Double Ratchet шлёт INITIATOR; определяем сторону по роли.
        if ca._service.role_of(conv_a) == Role.INITIATOR:
            sender, sconv, inbox = ca, conv_a, recv_b
        else:
            sender, sconv, inbox = cb, conv_b, recv_a
        await asyncio.to_thread(sender.send_message, sconv, "привет из gui")
        await _wait_for(lambda: inbox)
        assert inbox[0] == "привет из gui".encode("utf-8")
    finally:
        ca.lock()
        cb.lock()
        await server.stop()
