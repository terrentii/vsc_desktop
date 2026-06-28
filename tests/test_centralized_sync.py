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

    async def post_message(self, room_id, body, client_msg_id):
        if self.fail_post:
            raise NetworkError("down")
        self._post_id += 1
        m = RemoteMessage(id=self._post_id, room_id=room_id, sender="me",
                          body=body, created_at="t", client_msg_id=client_msg_id)
        self.posted.append(m)
        return m


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
