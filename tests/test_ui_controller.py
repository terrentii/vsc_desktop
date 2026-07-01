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


class _FakeP2PService:
    """Двойник P2PService: только то, что трогает controller."""

    def __init__(self, active_conv: int | None = None):
        self._active = active_conv
        self.sent_files: list[tuple] = []
        self.stopped: list[int] = []

    def has_session(self, conversation_id: int) -> bool:
        return conversation_id == self._active

    def send_file(self, conversation_id, filename, mime_type, data) -> None:
        self.sent_files.append((conversation_id, filename, mime_type, data))

    def stop_session(self, conversation_id: int) -> None:
        self.stopped.append(conversation_id)

    def stop(self) -> None:
        pass  # уборка при c.lock()


def test_send_file_local_fallback_without_active_session(tmp_path):
    c = _controller(tmp_path)
    c.create_vault(b"pw")
    conv = c.create_conversation("p2p")
    local_id = c.send_file(conv, "note.txt", "text/plain", b"hello")
    assert local_id is not None
    row = c.list_messages(conv)[0]
    assert row["kind"] == "file" and row["filename"] == "note.txt"
    assert row["mime_type"] == "text/plain" and row["body"] == b"hello"
    assert row["status"] == "local"
    c.lock()


def test_send_file_routes_through_active_session(tmp_path):
    c = _controller(tmp_path)
    c.create_vault(b"pw")
    conv = c.create_conversation("p2p")
    fake = _FakeP2PService(active_conv=conv)
    c.attach_service(fake)
    result = c.send_file(conv, "photo.png", "image/png", b"\x89PNG")
    assert result is None
    assert fake.sent_files == [(conv, "photo.png", "image/png", b"\x89PNG")]
    assert c.list_messages(conv) == []  # персист делает сама сессия, не controller
    c.lock()


def test_delete_conversation_removes_everything(tmp_path):
    from mys_crypto import primitives, ratchet

    c = _controller(tmp_path)
    c.create_vault(b"pw")
    conv = c.create_conversation("p2p")
    c.send_message(conv, "привет")
    _priv, pub = primitives.generate_x25519_keypair()
    c.vault.ratchet.save_state(conv, ratchet.ratchet_init_alice(b"k" * 32, pub))

    c.delete_conversation(conv)

    assert c.vault.conversations.get(conv) is None
    assert c.vault.messages.list(conv) == []
    assert c.vault.ratchet.load_state(conv) is None
    c.lock()


def test_delete_conversation_stops_active_session_first(tmp_path):
    c = _controller(tmp_path)
    c.create_vault(b"pw")
    conv = c.create_conversation("p2p")
    fake = _FakeP2PService(active_conv=conv)
    c.attach_service(fake)

    c.delete_conversation(conv)

    assert fake.stopped == [conv]
    assert c.vault.conversations.get(conv) is None
    c.lock()
