"""Юнит-тесты персиста и очистки централизованного аккаунта (без сети/потоков)."""

from mys_storage import create_vault

from mys_centralized import account
from mys_centralized.models import Session

FAST = {"time_cost": 1, "memory_cost": 8, "parallelism": 1}


def _vault(tmp_path):
    return create_vault(str(tmp_path / "v.db"), b"pw", params=FAST)


def test_wipe_on_logout_flag_default_and_roundtrip(tmp_path):
    v = _vault(tmp_path)
    try:
        assert account.load_wipe_on_logout(v) is False  # по умолчанию выключено
        account.save_wipe_on_logout(v, True)
        assert account.load_wipe_on_logout(v) is True
        account.save_wipe_on_logout(v, False)
        assert account.load_wipe_on_logout(v) is False
    finally:
        v.close()


def test_wipe_local_cache_clears_centralized_only(tmp_path):
    v = _vault(tmp_path)
    try:
        # Централизованная беседа с сообщением и курсором синка.
        c1 = v.conversations.add(mode="centralized", room_id=b"1", title="general")
        v.messages.add(c1, direction="in", body=b"hi", status="received", wire_seq=1)
        v.settings.set("central.cursor.1", b"5")
        # Сессия (тоже должна уйти отдельным clear_session — здесь проверяем wipe).
        account.save_session(v, Session(
            server_url="https://soufos.ru", username="alice", user_id=1, token="tok"))
        # Децентрализованная беседа — НЕ должна пострадать.
        c2 = v.conversations.add(mode="decentralized", title="p2p")
        v.messages.add(c2, direction="out", body=b"yo", status="local")

        account.wipe_local_cache(v)

        assert v.conversations.list(mode="centralized") == []
        assert v.messages.list(c1) == []
        assert v.settings.get("central.cursor.1") is None
        # P2P цел.
        assert len(v.conversations.list(mode="decentralized")) == 1
        assert len(v.messages.list(c2)) == 1
    finally:
        v.close()
