"""Интеграция оркестратора CentralizedService (этап 5).

In-process фейковый сервер: REST через httpx.MockTransport + WS через
websockets.serve на loopback. Блокирующие методы сервиса гоняем через
asyncio.to_thread, чтобы не стопорить loop теста (на нём живёт WS-сервер).
"""

import asyncio
import json

import httpx
import pytest
from websockets.asyncio.server import serve

from mys_storage import create_vault

from mys_centralized import account
from mys_centralized.service import CentralizedService
from mys_centralized.ws_client import WsClient


class FakeServer:
    """Минимальный сервер по контракту §5–§6: REST-обработчик + WS-обработчик."""

    def __init__(self):
        self.token = "tok-123"
        self.username = "alice"
        self.user_id = 7
        self.password = "pw"
        self.rooms = [{"id": 1, "name": "general", "is_direct": False, "updated_at": "t"}]
        self.history = {1: []}  # room_id -> list[dict]
        self._next_id = 100
        self._by_client = {}  # client_msg_id -> dict (идемпотентность)
        self.live: asyncio.Queue = asyncio.Queue()
        self.logged_out = False

    # -- REST (sync-обработчик для httpx.MockTransport) --------------------

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method = request.method
        if path == "/api/auth/login" and method == "POST":
            body = json.loads(request.content)
            if body.get("username") != self.username or body.get("password") != self.password:
                return httpx.Response(401, json={"error": "invalid_credentials"})
            return httpx.Response(200, json={
                "token": self.token,
                "user": {"id": self.user_id, "username": self.username},
            })
        if path == "/api/auth/logout" and method == "POST":
            self.logged_out = True
            return httpx.Response(204)
        # всё ниже требует Bearer
        if request.headers.get("Authorization") != f"Bearer {self.token}":
            return httpx.Response(401, json={"error": "unauthorized"})
        if path == "/api/rooms" and method == "GET":
            return httpx.Response(200, json={"rooms": self.rooms})
        if path.startswith("/api/rooms/") and path.endswith("/messages") and method == "GET":
            room_id = int(path.split("/")[3])
            after = request.url.params.get("after")
            msgs = self.history.get(room_id, [])
            if after is not None:
                msgs = [m for m in msgs if m["id"] > int(after)]
            return httpx.Response(200, json={"messages": msgs, "next_cursor": None})
        if path == "/api/messages" and method == "POST":
            body = json.loads(request.content)
            cid = body["client_msg_id"]
            if cid in self._by_client:
                return httpx.Response(200, json=self._by_client[cid])  # идемпотентность
            self._next_id += 1
            msg = {
                "id": self._next_id, "room_id": body["room_id"], "sender": self.username,
                "body": body["body"], "created_at": "t", "client_msg_id": cid,
            }
            self.history.setdefault(body["room_id"], []).append(msg)
            self._by_client[cid] = msg
            return httpx.Response(200, json=msg)
        return httpx.Response(404, json={"error": "not_found"})

    def add_history(self, room_id, body):
        self._next_id += 1
        m = {"id": self._next_id, "room_id": room_id, "sender": "bob",
             "body": body, "created_at": "t"}
        self.history.setdefault(room_id, []).append(m)
        return m

    # -- WS-обработчик -----------------------------------------------------

    async def ws_handler(self, ws):
        auth = json.loads(await ws.recv())
        if auth.get("type") != "auth" or auth.get("token") != self.token:
            await ws.send(json.dumps({"type": "error", "code": "unauthorized"}))
            return
        await ws.send(json.dumps({"type": "ready"}))

        async def pump():
            # Пушим live-кадры из очереди, пока соединение живо.
            while True:
                frame = await self.live.get()
                try:
                    await ws.send(json.dumps(frame))
                except Exception:
                    return

        task = asyncio.create_task(pump())
        try:
            await ws.wait_closed()  # завершится при закрытии клиентом (stop/logout)
        finally:
            task.cancel()


def _rest_factory(server):
    def make(base_url, *, token=None):
        from mys_centralized.api_client import RestClient
        client = httpx.AsyncClient(base_url=base_url, transport=httpx.MockTransport(server.handle))
        return RestClient(base_url, client=client, token=token)
    return make


def _ws_factory(url, token):
    return WsClient(url, token, ping_interval=None,
                    initial_backoff=0.01, max_backoff=0.05, jitter=0.0)


@pytest.fixture
def vault(tmp_path, fast_kdf):
    v = create_vault(str(tmp_path / "v.db"), b"pw", params=fast_kdf)
    yield v
    v.close()


async def _serve(server):
    s = await serve(server.ws_handler, "127.0.0.1", 0)
    port = s.sockets[0].getsockname()[1]
    return s, f"ws://127.0.0.1:{port}"


async def _wait_for(predicate, timeout=5.0):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.02)
    return False


def _make_service(vault, server, ws_url, **kw):
    return CentralizedService(
        vault, ws_url=ws_url,
        rest_factory=_rest_factory(server), ws_factory=_ws_factory, **kw,
    )


async def test_login_syncs_history_and_receives_live(vault):
    server = FakeServer()
    server.add_history(1, "hist-1")
    server.add_history(1, "hist-2")
    s, ws_url = await _serve(server)
    seen = []
    svc = _make_service(vault, server, ws_url,
                        on_message=lambda cid, lid: seen.append((cid, lid)))
    svc.start()
    try:
        sess = await asyncio.to_thread(svc.login, "http://srv", "alice", "pw")
        assert sess.username == "alice" and sess.token == server.token
        # первичный синк уже завершён к возврату login
        conv = vault.conversations.list("centralized")[0]["id"]
        assert [m["body"].decode() for m in vault.messages.list(conv)] == ["hist-1", "hist-2"]
        # сессия персистнута в зашифрованном vault
        assert account.load_session(vault) == sess
        # live-кадр через WS
        live = server.add_history(1, "live-1")
        await server.live.put({"type": "message", **live})
        assert await _wait_for(lambda: len(vault.messages.list(conv)) == 3)
        assert vault.messages.list(conv)[-1]["body"].decode() == "live-1"
        assert seen  # колбэк сработал на входящее
    finally:
        await asyncio.to_thread(svc.stop)
        s.close()
        await s.wait_closed()


async def test_send_message_persisted_and_echo_deduped(vault):
    server = FakeServer()
    s, ws_url = await _serve(server)
    svc = _make_service(vault, server, ws_url)
    svc.start()
    try:
        await asyncio.to_thread(svc.login, "http://srv", "alice", "pw")
        conv = vault.conversations.list("centralized")[0]["id"]
        local_id = await asyncio.to_thread(svc.send_message, conv, "hello")
        sent = vault.messages.list(conv)[0]
        assert sent["id"] == local_id
        assert sent["status"] == "sent" and sent["direction"] == "out"
        assert len(server.history[1]) == 1  # дошло до сервера
        # эхо собственного сообщения из WS не должно создать дубль
        posted = server.history[1][-1]
        await server.live.put({"type": "message", **posted})
        await asyncio.sleep(0.2)
        assert len(vault.messages.list(conv)) == 1
    finally:
        await asyncio.to_thread(svc.stop)
        s.close()
        await s.wait_closed()


async def test_login_bad_credentials_raises(vault):
    server = FakeServer()
    s, ws_url = await _serve(server)
    svc = _make_service(vault, server, ws_url)
    svc.start()
    try:
        from mys_centralized.errors import AuthError
        with pytest.raises(AuthError):
            await asyncio.to_thread(svc.login, "http://srv", "alice", "WRONG")
        assert account.load_session(vault) is None
    finally:
        await asyncio.to_thread(svc.stop)
        s.close()
        await s.wait_closed()


async def test_logout_clears_session(vault):
    server = FakeServer()
    s, ws_url = await _serve(server)
    svc = _make_service(vault, server, ws_url)
    svc.start()
    try:
        await asyncio.to_thread(svc.login, "http://srv", "alice", "pw")
        assert account.load_session(vault) is not None
        await asyncio.to_thread(svc.logout)
        assert account.load_session(vault) is None
        assert server.logged_out
    finally:
        await asyncio.to_thread(svc.stop)
        s.close()
        await s.wait_closed()


async def test_resume_from_saved_session(vault):
    server = FakeServer()
    server.add_history(1, "old")
    s, ws_url = await _serve(server)
    # заранее кладём сессию в vault (как после прошлого входа)
    from mys_centralized.models import Session
    account.save_session(vault, Session(
        server_url="http://srv", username="alice", user_id=7, token=server.token))
    svc = _make_service(vault, server, ws_url)
    svc.start()
    try:
        sess = await asyncio.to_thread(svc.resume)
        assert sess is not None and sess.token == server.token
        conv = vault.conversations.list("centralized")[0]["id"]
        assert [m["body"].decode() for m in vault.messages.list(conv)] == ["old"]
    finally:
        await asyncio.to_thread(svc.stop)
        s.close()
        await s.wait_closed()


async def test_resume_without_session_returns_none(vault):
    server = FakeServer()
    s, ws_url = await _serve(server)
    svc = _make_service(vault, server, ws_url)
    svc.start()
    try:
        assert await asyncio.to_thread(svc.resume) is None
    finally:
        await asyncio.to_thread(svc.stop)
        s.close()
        await s.wait_closed()
