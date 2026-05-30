"""Юнит-тесты WebSocket-клиента (этап 3). Реальный локальный сервер на loopback."""

import json
from contextlib import asynccontextmanager

import pytest
from websockets.asyncio.server import serve

from mys_centralized import AuthError
from mys_centralized.ws_client import WsClient


@asynccontextmanager
async def run_server(handler):
    server = await serve(handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        yield f"ws://127.0.0.1:{port}"
    finally:
        server.close()
        await server.wait_closed()


async def _collect(client, *, want_messages):
    got = []
    async for ev in client.events():
        if ev["type"] == "message":
            got.append(ev)
            if len(got) >= want_messages:
                client.close()
                break
    return got


async def test_auth_handshake_and_receive():
    async def handler(ws):
        auth = json.loads(await ws.recv())
        assert auth == {"type": "auth", "token": "tok"}
        await ws.send(json.dumps({"type": "ready"}))
        await ws.send(json.dumps({
            "type": "message", "room_id": 1, "id": 5,
            "sender": "bob", "body": "hi", "created_at": "t",
        }))
        await ws.wait_closed()

    async with run_server(handler) as url:
        client = WsClient(url, "tok", ping_interval=None)
        got = await _collect(client, want_messages=1)
        assert got[0]["id"] == 5
        assert got[0]["body"] == "hi"


async def test_ready_event_emitted_first():
    async def handler(ws):
        await ws.recv()
        await ws.send(json.dumps({"type": "ready"}))
        await ws.wait_closed()

    async with run_server(handler) as url:
        client = WsClient(url, "tok", ping_interval=None,
                          initial_backoff=0.01, max_backoff=0.02)
        async for ev in client.events():
            assert ev["type"] == "ready"
            client.close()
            break


async def test_bad_token_raises_auth_error():
    async def handler(ws):
        await ws.recv()
        await ws.send(json.dumps({"type": "error", "code": "unauthorized"}))
        await ws.wait_closed()

    async with run_server(handler) as url:
        client = WsClient(url, "bad", ping_interval=None)
        with pytest.raises(AuthError):
            async for _ in client.events():
                pass


async def test_reconnect_after_drop():
    state = {"conns": 0}

    async def handler(ws):
        state["conns"] += 1
        n = state["conns"]
        await ws.recv()
        await ws.send(json.dumps({"type": "ready"}))
        await ws.send(json.dumps({
            "type": "message", "room_id": 1, "id": n,
            "sender": "s", "body": f"m{n}", "created_at": "t",
        }))
        # закрываемся, возвращаясь из обработчика -> клиент должен переподключиться

    async with run_server(handler) as url:
        client = WsClient(url, "tok", ping_interval=None,
                          initial_backoff=0.01, max_backoff=0.05, jitter=0.0)
        got = await _collect(client, want_messages=2)
        assert [m["id"] for m in got] == [1, 2]
        assert state["conns"] >= 2
