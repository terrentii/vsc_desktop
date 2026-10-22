"""Вход в комнату «Центра» по 10-значному коду (POST /api/rooms/join)."""

import json

import httpx
import pytest

from mys_centralized import ServerError, account
from mys_centralized.api_client import RestClient
from mys_centralized.models import Room
from mys_centralized.sync import SyncEngine
from mys_storage import create_vault

BASE = "https://test.local"
ROOM = {"id": 7, "name": "проект", "is_direct": False, "updated_at": "t", "code": "1234567890"}


def make_client(handler):
    ac = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=BASE)
    return RestClient(BASE, client=ac, token="T")


async def test_rest_join_room_posts_code_and_parses_room():
    def handler(request):
        assert request.url.path == "/api/rooms/join"
        assert request.headers["Authorization"] == "Bearer T"
        assert json.loads(request.read()) == {"code": "1234567890"}
        return httpx.Response(200, json=ROOM)

    room = await make_client(handler).join_room("1234567890")
    assert (room.id, room.name, room.code) == (7, "проект", "1234567890")


async def test_rest_join_room_errors_map_to_server_error():
    rc = make_client(lambda r: httpx.Response(403, json={"error": "forbidden"}))
    with pytest.raises(ServerError, match="forbidden"):
        await rc.join_room("1234567890")


async def test_list_rooms_parses_code():
    rc = make_client(lambda r: httpx.Response(200, json={"rooms": [ROOM]}))
    assert (await rc.list_rooms())[0].code == "1234567890"


class FakeRest:
    def __init__(self):
        self.rooms = []

    async def list_rooms(self):
        return list(self.rooms)

    async def join_room(self, code):
        room = Room(id=7, name="проект", code=code)
        self.rooms.append(room)
        return room

    async def get_messages(self, room_id, *, after=None, limit=None):
        return [], None


@pytest.fixture
def vault(tmp_path, fast_kdf):
    v = create_vault(str(tmp_path / "v.db"), b"pw", params=fast_kdf)
    yield v
    v.close()


async def test_sync_join_creates_conversation_and_remembers_code(vault):
    eng = SyncEngine(vault, FakeRest())
    conv = await eng.join_room("1234567890")
    assert vault.conversations.get(conv)["title"] == "проект"
    assert eng.room_code(conv) == "1234567890"
    assert await eng.join_room("1234567890") == conv  # повторный вход — та же беседа


async def test_sync_rooms_remembers_codes_and_wipe_forgets(vault):
    rest = FakeRest()
    rest.rooms = [Room(id=3, name="г", code="5555555555")]
    eng = SyncEngine(vault, rest)
    conv = (await eng.sync_rooms())[3]
    assert eng.room_code(conv) == "5555555555"
    account.wipe_local_cache(vault)
    assert vault.settings.get("central.code.3") is None
