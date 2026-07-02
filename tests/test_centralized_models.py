"""Юнит-тесты моделей и ошибок централизованного модуля (этап 1)."""

import pytest

from mys_centralized import (
    AuthError,
    CentralizedError,
    NetworkError,
    ProtocolError,
    RemoteMessage,
    Room,
    ServerError,
    Session,
    SyncCursor,
)


def test_session_fields():
    s = Session(server_url="https://soufos.ru", username="alice", user_id=7, token="tok")
    assert s.username == "alice"
    assert s.user_id == 7
    assert s.token == "tok"


def test_room_defaults():
    r = Room(id=1)
    assert r.name is None
    assert r.is_direct is False
    assert r.updated_at is None


def test_remote_message_roundtrip_fields():
    m = RemoteMessage(
        id=10, room_id=2, sender="bob", body="hi", created_at="2026-05-30T12:00:00",
        client_msg_id="c-1",
    )
    assert m.room_id == 2
    assert m.client_msg_id == "c-1"
    assert m.media is None


def test_remote_message_media_field():
    m = RemoteMessage(
        id=11, room_id=2, sender="bob", body="", created_at="2026-05-30T12:00:00",
        media="abc123_photo.png",
    )
    assert m.media == "abc123_photo.png"


def test_cursor_serialization():
    assert SyncCursor(room_id=1, last_id=None).to_str() == ""
    assert SyncCursor(room_id=1, last_id=42).to_str() == "42"
    assert SyncCursor.from_str(1, None).last_id is None
    assert SyncCursor.from_str(1, "").last_id is None
    assert SyncCursor.from_str(1, "42").last_id == 42


def test_error_hierarchy():
    for exc in (AuthError, ServerError, NetworkError, ProtocolError):
        assert issubclass(exc, CentralizedError)
    assert not issubclass(CentralizedError, AuthError)


def test_errors_are_raisable():
    with pytest.raises(CentralizedError):
        raise AuthError("nope")
