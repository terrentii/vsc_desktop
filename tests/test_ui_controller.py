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


from mys_ui.controller import DECENTRALIZED


class _FakeP2P:
    """Фейковый P2P-сервис: фиксирует жизненный цикл без сети."""

    def __init__(self, vault, rendezvous_url, *, on_message, on_state_change, on_error):
        self.vault = vault
        self.url = rendezvous_url
        self.on_message = on_message
        self.started = False
        self.stopped = False
        self.sessions: dict[int, str] = {}

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def start_session(self, phrase, *, timeout=None):
        cid = len(self.sessions) + 1
        self.sessions[cid] = phrase
        return cid

    def has_session(self, cid):
        return cid in self.sessions


def _p2p_ready(tmp_path):
    built: list[_FakeP2P] = []

    def factory(vault, rendezvous_url, **cb):
        svc = _FakeP2P(vault, rendezvous_url, **cb)
        built.append(svc)
        return svc

    c = AppController(str(tmp_path / "v.db"), kdf_params=FAST, p2p_factory=factory)
    c.create_vault(b"pw")
    c.set_mode(DECENTRALIZED)
    return c, built


def test_ensure_p2p_service_builds_and_starts(tmp_path):
    c, built = _p2p_ready(tmp_path)
    svc = c.ensure_p2p_service("ws://a:1/p2p")
    assert built == [svc]
    assert svc.started is True
    assert svc.url == "ws://a:1/p2p"


def test_ensure_p2p_service_reuses_same_url(tmp_path):
    c, built = _p2p_ready(tmp_path)
    s1 = c.ensure_p2p_service("ws://a:1/p2p")
    s2 = c.ensure_p2p_service("ws://a:1/p2p")
    assert s1 is s2
    assert len(built) == 1


def test_ensure_p2p_service_switches_url_stops_old(tmp_path):
    c, built = _p2p_ready(tmp_path)
    s1 = c.ensure_p2p_service("ws://a:1/p2p")
    s2 = c.ensure_p2p_service("ws://b:2/p2p")
    assert s1.stopped is True
    assert s2 is not s1
    assert len(built) == 2


def test_create_conversation_routes_to_start_session(tmp_path):
    c, built = _p2p_ready(tmp_path)
    cid = c.create_conversation(
        "фраза", room_phrase="общая фраза", rendezvous_url="ws://a:1/p2p"
    )
    assert built[0].sessions[cid] == "общая фраза"


def test_lock_stops_p2p_service(tmp_path):
    c, built = _p2p_ready(tmp_path)
    svc = c.ensure_p2p_service("ws://a:1/p2p")
    c.lock()
    assert svc.stopped is True


def test_p2p_observer_receives_message(tmp_path):
    c, _ = _p2p_ready(tmp_path)
    seen: list[tuple] = []
    c.add_p2p_observer(
        on_message=lambda cid, body: seen.append((cid, body)),
        on_state_change=None,
        on_error=None,
    )
    c._p2p_on_message(7, b"hi")
    assert seen == [(7, b"hi")]
