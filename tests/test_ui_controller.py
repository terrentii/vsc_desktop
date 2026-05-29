import pytest

from mys_storage import VaultLocked, WrongPassword
from mys_ui.controller import AppController

FAST = {"time_cost": 1, "memory_cost": 8, "parallelism": 1}


def _controller(tmp_path):
    return AppController(str(tmp_path / "vault.db"), kdf_params=FAST)


def test_vault_exists_reflects_filesystem(tmp_path):
    c = _controller(tmp_path)
    assert c.vault_exists() is False
    c.create_vault(b"pw")
    assert c.vault_exists() is True
    c.lock()


def test_create_then_unlock(tmp_path):
    c = _controller(tmp_path)
    c.create_vault(b"pw")
    c.lock()
    assert c.vault is None
    c.unlock(b"pw")
    assert c.vault is not None
    c.lock()


def test_unlock_wrong_password_raises(tmp_path):
    c = _controller(tmp_path)
    c.create_vault(b"right")
    c.lock()
    with pytest.raises(WrongPassword):
        c.unlock(b"wrong")


def test_conversations_filtered_by_mode(tmp_path):
    c = _controller(tmp_path)
    c.create_vault(b"pw")
    c.set_mode("decentralized")
    c.create_conversation("p2p chat")
    c.set_mode("centralized")
    c.create_conversation("server room")
    assert [x["title"] for x in c.list_conversations()] == ["server room"]
    c.set_mode("decentralized")
    assert [x["title"] for x in c.list_conversations()] == ["p2p chat"]
    c.lock()


def test_send_and_list_messages(tmp_path):
    c = _controller(tmp_path)
    c.create_vault(b"pw")
    conv = c.create_conversation("chat")
    c.send_message(conv, "привет")
    c.send_message(conv, "как дела")
    msgs = c.list_messages(conv)
    assert [m["body"].decode() for m in msgs] == ["привет", "как дела"]
    assert msgs[0]["direction"] == "out" and msgs[0]["status"] == "local"
    c.lock()


def test_change_password(tmp_path):
    c = _controller(tmp_path)
    c.create_vault(b"old")
    c.change_password(b"old", b"new")
    c.lock()
    c.unlock(b"new")
    assert c.vault is not None
    c.lock()
