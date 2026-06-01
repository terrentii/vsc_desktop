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
