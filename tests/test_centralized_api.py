"""Юнит-тесты REST-клиента централизованного модуля (этап 2).

Сервер эмулируется httpx.MockTransport — без сети.
"""

import httpx
import pytest

from mys_centralized import AuthError, NetworkError, ProtocolError, ServerError
from mys_centralized.api_client import RestClient

BASE = "https://test.local"


def make_client(handler, *, token=None):
    transport = httpx.MockTransport(handler)
    ac = httpx.AsyncClient(transport=transport, base_url=BASE)
    return RestClient(BASE, client=ac, token=token)


async def test_login_sets_token_and_returns_session():
    def handler(request):
        assert request.url.path == "/api/auth/login"
        assert "Authorization" not in request.headers
        return httpx.Response(200, json={"token": "T1", "user": {"id": 5, "username": "alice"}})

    rc = make_client(handler)
    sess = await rc.login("alice", "pw")
    assert sess.token == "T1"
    assert sess.user_id == 5
    assert sess.username == "alice"
    assert rc.token == "T1"


async def test_register_returns_session():
    def handler(request):
        assert request.url.path == "/api/auth/register"
        return httpx.Response(201, json={"token": "T2", "user": {"id": 9, "username": "bob"}})

    rc = make_client(handler)
    sess = await rc.register("bob", "pw")
    assert sess.user_id == 9
    assert rc.token == "T2"


async def test_login_wrong_password_raises_auth():
    def handler(request):
        return httpx.Response(401, json={"error": "unauthorized"})

    rc = make_client(handler)
    with pytest.raises(AuthError):
        await rc.login("alice", "bad")


async def test_register_conflict_raises_server_error():
    def handler(request):
        return httpx.Response(409, json={"error": "username_taken"})

    rc = make_client(handler)
    with pytest.raises(ServerError) as ei:
        await rc.register("alice", "pw")
    assert "username_taken" in str(ei.value)


async def test_5xx_is_network_error():
    def handler(request):
        return httpx.Response(503, text="oops")

    rc = make_client(handler, token="T")
    with pytest.raises(NetworkError):
        await rc.list_rooms()


async def test_transport_failure_is_network_error():
    def handler(request):
        raise httpx.ConnectError("no route")

    rc = make_client(handler, token="T")
    with pytest.raises(NetworkError):
        await rc.list_rooms()


async def test_bad_json_is_protocol_error():
    def handler(request):
        return httpx.Response(200, text="not json", headers={"content-type": "text/plain"})

    rc = make_client(handler, token="T")
    with pytest.raises(ProtocolError):
        await rc.list_rooms()


async def test_list_rooms_sends_bearer_and_parses():
    def handler(request):
        assert request.headers["Authorization"] == "Bearer T"
        return httpx.Response(200, json={"rooms": [
            {"id": 1, "name": "general", "is_direct": False},
            {"id": 2, "name": None, "is_direct": True, "updated_at": "2026-05-30T00:00:00"},
        ]})

    rc = make_client(handler, token="T")
    rooms = await rc.list_rooms()
    assert [r.id for r in rooms] == [1, 2]
    assert rooms[1].is_direct is True
    assert rooms[1].updated_at == "2026-05-30T00:00:00"


async def test_get_messages_pagination_and_cursor():
    def handler(request):
        assert request.url.params.get("after") == "10"
        assert request.url.params.get("limit") == "2"
        return httpx.Response(200, json={
            "messages": [
                {"id": 11, "room_id": 3, "sender": "bob", "body": "a", "created_at": "t1"},
                {"id": 12, "room_id": 3, "sender": "alice", "body": "b", "created_at": "t2"},
            ],
            "next_cursor": 12,
        })

    rc = make_client(handler, token="T")
    msgs, cursor = await rc.get_messages(3, after=10, limit=2)
    assert [m.id for m in msgs] == [11, 12]
    assert cursor == 12


async def test_get_messages_fills_room_id_when_missing():
    def handler(request):
        return httpx.Response(200, json={
            "messages": [{"id": 1, "sender": "x", "body": "y", "created_at": "t"}],
            "next_cursor": None,
        })

    rc = make_client(handler, token="T")
    msgs, cursor = await rc.get_messages(7)
    assert msgs[0].room_id == 7
    assert cursor is None


async def test_post_message_idempotent_echo():
    seen = []

    def handler(request):
        import json
        payload = json.loads(request.content)
        seen.append(payload["client_msg_id"])
        # сервер возвращает ту же запись на повтор client_msg_id
        return httpx.Response(200, json={
            "id": 100, "room_id": payload["room_id"], "sender": "alice",
            "body": payload["body"], "created_at": "t", "client_msg_id": payload["client_msg_id"],
        })

    rc = make_client(handler, token="T")
    m1 = await rc.post_message(4, "hi", "c-1")
    m2 = await rc.post_message(4, "hi", "c-1")
    assert m1.id == m2.id == 100
    assert m1.client_msg_id == "c-1"
    assert seen == ["c-1", "c-1"]


async def test_logout_clears_token_even_on_error():
    def handler(request):
        return httpx.Response(500)

    rc = make_client(handler, token="T")
    with pytest.raises(NetworkError):
        await rc.logout()
    assert rc.token is None


# ── вложения ───────────────────────────────────────────────────────────────────

async def test_get_messages_parses_media_field():
    def handler(request):
        return httpx.Response(200, json={
            "messages": [
                {"id": 1, "room_id": 7, "sender": "x", "body": "", "created_at": "t",
                 "media": "abc_photo.png"},
                {"id": 2, "room_id": 7, "sender": "x", "body": "hi", "created_at": "t"},
            ],
            "next_cursor": None,
        })

    rc = make_client(handler, token="T")
    msgs, _cursor = await rc.get_messages(7)
    assert msgs[0].media == "abc_photo.png"
    assert msgs[1].media is None


async def test_post_message_includes_media_in_request_json():
    seen = []

    def handler(request):
        import json
        payload = json.loads(request.content)
        seen.append(payload)
        return httpx.Response(200, json={
            "id": 1, "room_id": payload["room_id"], "sender": "alice",
            "body": payload["body"], "created_at": "t",
            "client_msg_id": payload["client_msg_id"], "media": payload.get("media"),
        })

    rc = make_client(handler, token="T")
    msg = await rc.post_message(4, "", "c-1", media="abc_photo.png")
    assert seen[0]["media"] == "abc_photo.png"
    assert msg.media == "abc_photo.png"


async def test_post_message_omits_media_when_not_given():
    def handler(request):
        import json
        payload = json.loads(request.content)
        assert "media" not in payload
        return httpx.Response(200, json={
            "id": 1, "room_id": payload["room_id"], "sender": "alice",
            "body": payload["body"], "created_at": "t",
            "client_msg_id": payload["client_msg_id"],
        })

    rc = make_client(handler, token="T")
    await rc.post_message(4, "hi", "c-1")


async def test_upload_media_sends_multipart_and_parses_response():
    def handler(request):
        assert request.url.path == "/api/rooms/4/media"
        assert request.headers["Authorization"] == "Bearer T"
        return httpx.Response(201, json={"ok": True, "filename": "abc_photo.png",
                                          "mime_type": "image/png", "size": 5})

    rc = make_client(handler, token="T")
    result = await rc.upload_media(4, "photo.png", b"\x89PNG\r", "image/png")
    assert result == {"filename": "abc_photo.png", "mime_type": "image/png", "size": 5}


async def test_download_media_returns_bytes_and_content_type():
    def handler(request):
        assert request.url.path == "/api/rooms/4/media/abc_photo.png"
        return httpx.Response(200, content=b"raw-bytes", headers={"content-type": "image/png"})

    rc = make_client(handler, token="T")
    data, mime = await rc.download_media(4, "abc_photo.png")
    assert data == b"raw-bytes"
    assert mime == "image/png"
