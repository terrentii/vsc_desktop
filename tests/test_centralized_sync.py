"""Тесты движка синхронизации и персиста сессии (этап 4)."""

import pytest

from mys_storage import create_vault

from mys_centralized import account
from mys_centralized.errors import NetworkError
from mys_centralized.models import RemoteMessage, Room, Session
from mys_centralized.sync import SyncEngine


class FakeRest:
    def __init__(self):
        self.rooms: list[Room] = []
        self.history: dict[int, list[RemoteMessage]] = {}
        self.posted: list[RemoteMessage] = []
        self._post_id = 1000
        self.fail_post = False
        self.uploaded: list[tuple] = []
        self.media_store: dict[str, bytes] = {}

    async def list_rooms(self):
        return list(self.rooms)

    async def get_messages(self, room_id, *, after=None, limit=None):
        msgs = list(self.history.get(room_id, []))
        if after is not None:
            msgs = [m for m in msgs if m.id > after]
        if limit is not None and len(msgs) > limit:
            page = msgs[:limit]
            return page, page[-1].id
        return msgs, None

    async def post_message(self, room_id, body, client_msg_id, *, media=None, reply_to=None):
        if self.fail_post:
            raise NetworkError("down")
        self._post_id += 1
        m = RemoteMessage(id=self._post_id, room_id=room_id, sender="me",
                          body=body, created_at="t", client_msg_id=client_msg_id,
                          media=media)
        self.posted.append(m)
        self.posted_replies = getattr(self, "posted_replies", [])
        self.posted_replies.append(reply_to)
        return m

    async def edit_message(self, message_id, body):
        self.edited = getattr(self, "edited", [])
        self.edited.append((message_id, body))

    async def delete_message(self, message_id):
        self.deleted = getattr(self, "deleted", [])
        self.deleted.append(message_id)

    async def upload_media(self, room_id, filename, data, mime_type):
        server_name = f"srv_{filename}"
        self.media_store[server_name] = data
        self.uploaded.append((room_id, filename, mime_type))
        return {"filename": server_name, "mime_type": mime_type, "size": len(data)}

    async def download_media(self, room_id, filename):
        return self.media_store[filename], "application/octet-stream"


@pytest.fixture
def vault(tmp_path, fast_kdf):
    v = create_vault(str(tmp_path / "v.db"), b"pw", params=fast_kdf)
    yield v
    v.close()


async def test_sync_rooms_upserts_without_duplicates(vault):
    rest = FakeRest()
    rest.rooms = [Room(id=1, name="general"), Room(id=2, name="dm", is_direct=True)]
    eng = SyncEngine(vault, rest)
    mapping = await eng.sync_rooms()
    assert set(mapping) == {1, 2}
    assert len(vault.conversations.list("centralized")) == 2
    mapping2 = await eng.sync_rooms()
    assert mapping2 == mapping
    assert len(vault.conversations.list("centralized")) == 2


async def test_sync_history_persists_and_advances_cursor(vault):
    rest = FakeRest()
    rest.rooms = [Room(id=1, name="g")]
    rest.history[1] = [
        RemoteMessage(id=i, room_id=1, sender="x", body=f"m{i}", created_at="t")
        for i in (1, 2, 3)
    ]
    eng = SyncEngine(vault, rest, page_limit=2)
    await eng.sync_rooms()
    conv = await eng.sync_history(1)
    assert [m["body"].decode() for m in vault.messages.list(conv)] == ["m1", "m2", "m3"]
    # курсор продвинут — повторная дозагрузка ничего не добавляет
    await eng.sync_history(1)
    assert len(vault.messages.list(conv)) == 3


async def test_offline_catchup_after_cursor(vault):
    rest = FakeRest()
    rest.rooms = [Room(id=1, name="g")]
    rest.history[1] = [RemoteMessage(id=1, room_id=1, sender="x", body="a", created_at="t")]
    eng = SyncEngine(vault, rest)
    await eng.sync_rooms()
    conv = await eng.sync_history(1)
    assert len(vault.messages.list(conv)) == 1
    # «оффлайн»: на сервере появились новые
    rest.history[1] += [
        RemoteMessage(id=2, room_id=1, sender="x", body="b", created_at="t"),
        RemoteMessage(id=3, room_id=1, sender="x", body="c", created_at="t"),
    ]
    await eng.sync_history(1)
    assert [m["body"].decode() for m in vault.messages.list(conv)] == ["a", "b", "c"]


async def test_dedup_by_server_id(vault):
    rest = FakeRest()
    rest.rooms = [Room(id=1, name="g")]
    eng = SyncEngine(vault, rest)
    await eng.sync_rooms()
    frame = {"type": "message", "room_id": 1, "id": 50,
             "sender": "x", "body": "hi", "created_at": "t"}
    await eng.ingest_ws(frame)
    await eng.ingest_ws(dict(frame))
    conv = eng._conv_for_room(1)
    assert len(vault.messages.list(conv)) == 1


async def test_send_marks_sent_and_echo_is_deduped(vault):
    rest = FakeRest()
    rest.rooms = [Room(id=1, name="g")]
    eng = SyncEngine(vault, rest)
    mapping = await eng.sync_rooms()
    conv = mapping[1]
    await eng.send(conv, "hello")
    msgs = vault.messages.list(conv)
    assert len(msgs) == 1
    sent = msgs[0]
    assert sent["status"] == "sent" and sent["direction"] == "out"
    server_id = sent["wire_seq"]
    echo = {"type": "message", "room_id": 1, "id": server_id, "sender": "me",
            "body": "hello", "created_at": "t", "client_msg_id": sent["client_msg_id"]}
    await eng.ingest_ws(echo)
    assert len(vault.messages.list(conv)) == 1


async def test_ingest_links_pending_out_by_client_id(vault):
    rest = FakeRest()
    rest.rooms = [Room(id=1, name="g")]
    eng = SyncEngine(vault, rest)
    mapping = await eng.sync_rooms()
    conv = mapping[1]
    cid = "abc"
    vault.messages.add(conv, direction="out", body=b"hi", status="pending", client_msg_id=cid)
    frame = {"type": "message", "room_id": 1, "id": 77, "sender": "me",
             "body": "hi", "created_at": "t", "client_msg_id": cid}
    await eng.ingest_ws(frame)
    msgs = vault.messages.list(conv)
    assert len(msgs) == 1
    assert msgs[0]["wire_seq"] == 77
    assert msgs[0]["status"] == "sent"


async def test_own_echo_without_client_id_deduped_by_body(vault):
    # Сервер в WS-кадре не присылает client_msg_id, а эхо приходит ДО mark_sent
    # (wire_seq ещё None) — дедуп должен сработать по телу+отправителю, без дубля.
    rest = FakeRest()
    rest.rooms = [Room(id=1, name="g")]
    eng = SyncEngine(vault, rest, own_username="me")
    conv = (await eng.sync_rooms())[1]
    vault.messages.add(conv, direction="out", body=b"hi", status="pending",
                       client_msg_id="cid-1")  # отправлено, ответ POST ещё не пришёл
    echo = {"type": "message", "room_id": 1, "id": 77, "sender": "me",
            "body": "hi", "created_at": "t"}  # client_msg_id отсутствует
    await eng.ingest_ws(echo)
    msgs = vault.messages.list(conv)
    assert len(msgs) == 1
    assert msgs[0]["wire_seq"] == 77 and msgs[0]["direction"] == "out"


async def test_identical_own_messages_not_collapsed(vault):
    # Два одинаковых исходящих не должны схлопнуться: каждое эхо линкуется со
    # старейшим неподтверждённым, после чего у него проставлен wire_seq.
    rest = FakeRest()
    rest.rooms = [Room(id=1, name="g")]
    eng = SyncEngine(vault, rest, own_username="me")
    conv = (await eng.sync_rooms())[1]
    vault.messages.add(conv, direction="out", body=b"x", status="pending", client_msg_id="a")
    vault.messages.add(conv, direction="out", body=b"x", status="pending", client_msg_id="b")
    await eng.ingest_ws({"type": "message", "room_id": 1, "id": 10, "sender": "me",
                         "body": "x", "created_at": "t"})
    await eng.ingest_ws({"type": "message", "room_id": 1, "id": 11, "sender": "me",
                         "body": "x", "created_at": "t"})
    wires = sorted(m["wire_seq"] for m in vault.messages.list(conv))
    assert wires == [10, 11]


async def test_send_failure_marks_failed(vault):
    rest = FakeRest()
    rest.rooms = [Room(id=1, name="g")]
    rest.fail_post = True
    eng = SyncEngine(vault, rest)
    conv = (await eng.sync_rooms())[1]
    with pytest.raises(NetworkError):
        await eng.send(conv, "x")
    assert vault.messages.list(conv)[0]["status"] == "failed"


async def test_on_message_callback_invoked_for_incoming(vault):
    rest = FakeRest()
    rest.rooms = [Room(id=1, name="g")]
    seen = []
    eng = SyncEngine(vault, rest, on_message=lambda c, lid, m: seen.append((c, m.id)))
    await eng.sync_rooms()
    await eng.ingest_ws({"type": "message", "room_id": 1, "id": 9,
                         "sender": "x", "body": "y", "created_at": "t"})
    assert seen and seen[0][1] == 9


def test_account_session_roundtrip(vault):
    s = Session(server_url="https://soufos.ru", username="a", user_id=3, token="tok")
    account.save_session(vault, s)
    assert account.load_session(vault) == s
    account.clear_session(vault)
    assert account.load_session(vault) is None


# ── вложения ───────────────────────────────────────────────────────────────────

async def test_ingest_media_message_stores_lazy_placeholder_no_body(vault):
    rest = FakeRest()
    rest.rooms = [Room(id=1, name="g")]
    eng = SyncEngine(vault, rest)
    conv = (await eng.sync_rooms())[1]
    await eng.ingest_ws({"type": "message", "room_id": 1, "id": 5, "sender": "x",
                         "body": "", "created_at": "t", "media": "abc_photo.png"})
    row = vault.messages.list(conv)[0]
    assert row["kind"] == "image"
    assert row["filename"] == "photo.png"
    assert row["media_ref"] == "abc_photo.png"
    assert row["body"] is None


async def test_send_file_uploads_then_posts_with_media_and_stores_body_eagerly(vault):
    rest = FakeRest()
    rest.rooms = [Room(id=1, name="g")]
    eng = SyncEngine(vault, rest)
    conv = (await eng.sync_rooms())[1]
    local_id = await eng.send_file(conv, "photo.png", "image/png", b"\x89PNG-data")
    assert rest.uploaded == [(1, "photo.png", "image/png")]
    row = vault.messages.get(local_id)
    assert row["kind"] == "image"
    assert row["body"] == b"\x89PNG-data"
    assert row["status"] == "sent"
    assert row["media_ref"] == "srv_photo.png"


async def test_send_file_rejects_oversized(vault, monkeypatch):
    from mys_centralized import media as media_mod
    monkeypatch.setattr(media_mod, "MAX_MEDIA_SIZE", 4)
    rest = FakeRest()
    rest.rooms = [Room(id=1, name="g")]
    eng = SyncEngine(vault, rest)
    conv = (await eng.sync_rooms())[1]
    with pytest.raises(ValueError):
        await eng.send_file(conv, "big.png", "image/png", b"12345")
    assert rest.uploaded == []


async def test_send_file_rejects_bad_extension(vault):
    rest = FakeRest()
    rest.rooms = [Room(id=1, name="g")]
    eng = SyncEngine(vault, rest)
    conv = (await eng.sync_rooms())[1]
    with pytest.raises(ValueError):
        await eng.send_file(conv, "evil.svg", "image/svg+xml", b"<svg/>")
    assert rest.uploaded == []


async def test_fetch_media_downloads_and_backfills_body(vault):
    rest = FakeRest()
    rest.rooms = [Room(id=1, name="g")]
    eng = SyncEngine(vault, rest)
    conv = (await eng.sync_rooms())[1]
    rest.media_store["abc_photo.png"] = b"real-bytes"
    mid = vault.messages.add(
        conv, direction="in", body=None, status="received", kind="image",
        filename="photo.png", mime_type="image/png", media_ref="abc_photo.png",
    )
    data = await eng.fetch_media(mid)
    assert data == b"real-bytes"
    assert vault.messages.get(mid)["body"] == b"real-bytes"


async def test_fetch_media_returns_cached_body_without_refetch(vault):
    rest = FakeRest()
    rest.rooms = [Room(id=1, name="g")]
    eng = SyncEngine(vault, rest)
    conv = (await eng.sync_rooms())[1]
    mid = vault.messages.add(
        conv, direction="in", body=b"already-here", status="received", kind="image",
        filename="photo.png", mime_type="image/png", media_ref="abc_photo.png",
    )
    data = await eng.fetch_media(mid)
    assert data == b"already-here"
    assert "abc_photo.png" not in rest.media_store  # никогда не скачивалось


async def test_ingest_persists_server_created_at_as_received_at(vault):
    # Серверное время сообщения — авторитетное: история после синка должна
    # показывать время отправки, а не момент синхронизации.
    rest = FakeRest()
    rest.rooms = [Room(id=1, name="g")]
    eng = SyncEngine(vault, rest)
    await eng.sync_rooms()
    await eng.ingest_ws({
        "type": "message", "room_id": 1, "id": 7, "sender": "x",
        "body": "hi", "created_at": "2026-05-13T12:27:00",
    })
    conv = eng._conv_for_room(1)
    row = vault.messages.list(conv)[0]
    from datetime import datetime, timezone
    expected = datetime(2026, 5, 13, 12, 27, tzinfo=timezone.utc).timestamp()
    assert row["received_at"] == expected


async def test_ingest_unparseable_created_at_falls_back_to_local_clock(vault):
    import time as _time

    rest = FakeRest()
    rest.rooms = [Room(id=1, name="g")]
    eng = SyncEngine(vault, rest)
    await eng.sync_rooms()
    before = _time.time()
    await eng.ingest_ws({
        "type": "message", "room_id": 1, "id": 8, "sender": "x",
        "body": "hi", "created_at": "t",
    })
    conv = eng._conv_for_room(1)
    row = vault.messages.list(conv)[0]
    assert before <= row["received_at"] <= _time.time()


# ── ответы (reply), правка и удаление ────────────────────────────────────────

async def test_send_with_reply_persists_quote_and_passes_wire_id(vault):
    rest = FakeRest()
    rest.rooms = [Room(id=1, name="g")]
    eng = SyncEngine(vault, rest)
    conv = (await eng.sync_rooms())[1]
    local_id = await eng.send(conv, "ответ", reply={
        "wire": 77, "sender": "Skuf", "snippet": "это же наш любимый форум",
    })
    row = vault.messages.get(local_id)
    assert row["reply_author"] == "Skuf"
    assert row["reply_snippet"] == "это же наш любимый форум"
    assert rest.posted_replies == [77]


async def test_ingest_persists_server_reply_quote(vault):
    rest = FakeRest()
    rest.rooms = [Room(id=1, name="g")]
    eng = SyncEngine(vault, rest)
    await eng.sync_rooms()
    await eng.ingest_ws({
        "type": "message", "room_id": 1, "id": 5, "sender": "x", "body": "ok",
        "created_at": "t", "reply_to": {"id": 3, "sender": "y", "body": "цитата"},
    })
    conv = eng._conv_for_room(1)
    row = vault.messages.list(conv)[0]
    assert row["reply_author"] == "y" and row["reply_snippet"] == "цитата"


async def test_edit_updates_server_then_local_body(vault):
    rest = FakeRest()
    rest.rooms = [Room(id=1, name="g")]
    eng = SyncEngine(vault, rest)
    conv = (await eng.sync_rooms())[1]
    local_id = await eng.send(conv, "старое")
    await eng.edit(local_id, "новое")
    wire = vault.messages.get(local_id)["wire_seq"]
    assert rest.edited == [(wire, "новое")]
    assert vault.messages.get(local_id)["body"] == "новое".encode()


async def test_delete_removes_server_then_local_row(vault):
    rest = FakeRest()
    rest.rooms = [Room(id=1, name="g")]
    eng = SyncEngine(vault, rest)
    conv = (await eng.sync_rooms())[1]
    local_id = await eng.send(conv, "прощай")
    wire = vault.messages.get(local_id)["wire_seq"]
    await eng.delete(local_id)
    assert rest.deleted == [wire]
    assert vault.messages.get(local_id) is None


async def test_edit_unconfirmed_message_raises(vault):
    rest = FakeRest()
    rest.rooms = [Room(id=1, name="g")]
    eng = SyncEngine(vault, rest)
    conv = (await eng.sync_rooms())[1]
    local_id = vault.messages.add(conv, direction="out", body=b"x", status="pending")
    with pytest.raises(ValueError):
        await eng.edit(local_id, "y")


async def test_apply_ws_edit_and_delete(vault):
    rest = FakeRest()
    rest.rooms = [Room(id=1, name="g")]
    eng = SyncEngine(vault, rest)
    await eng.sync_rooms()
    await eng.ingest_ws({"type": "message", "room_id": 1, "id": 9,
                         "sender": "x", "body": "было", "created_at": "t"})
    conv = eng._conv_for_room(1)

    assert eng.apply_ws_edit({"room_id": 1, "id": 9, "body": "стало"}) == conv
    assert vault.messages.list(conv)[0]["body"] == "стало".encode()

    assert eng.apply_ws_delete({"room_id": 1, "id": 9}) == conv
    assert vault.messages.list(conv) == []

    # неизвестный id / комната — тихий None
    assert eng.apply_ws_edit({"room_id": 1, "id": 404, "body": "x"}) is None
    assert eng.apply_ws_delete({"room_id": 99, "id": 9}) is None


async def test_send_notifies_on_pending_and_sent(vault):
    # Оптимистичная отправка: UI получает уведомление сразу при записи pending
    # и повторно после подтверждения сервером.
    rest = FakeRest()
    rest.rooms = [Room(id=1, name="g")]
    seen = []
    eng = SyncEngine(vault, rest, on_message=lambda c, l, m: seen.append(
        vault.messages.get(l)["status"]
    ))
    conv = (await eng.sync_rooms())[1]
    await eng.send(conv, "мгновенно")
    assert seen == ["pending", "sent"]


async def test_send_failure_notifies_failed(vault):
    rest = FakeRest()
    rest.rooms = [Room(id=1, name="g")]
    rest.fail_post = True
    seen = []
    eng = SyncEngine(vault, rest, on_message=lambda c, l, m: seen.append(
        vault.messages.get(l)["status"]
    ))
    conv = (await eng.sync_rooms())[1]
    with pytest.raises(NetworkError):
        await eng.send(conv, "не дойдёт")
    assert seen == ["pending", "failed"]
