"""REST-клиент централизованного режима поверх httpx.AsyncClient.

Знает только HTTP-контракт сервера (§5 спеки) и маппинг статусов в типизированные
ошибки. Ничего не знает о хранилище/UI.
"""

from __future__ import annotations

import httpx

from .errors import AuthError, NetworkError, ProtocolError, ServerError
from .models import RemoteMessage, Room, Session


class RestClient:
    def __init__(
        self,
        base_url: str,
        *,
        client: httpx.AsyncClient | None = None,
        token: str | None = None,
        timeout: float = 10.0,
    ):
        self._base = base_url.rstrip("/")
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(base_url=self._base, timeout=timeout)
        self._token = token

    @property
    def token(self) -> str | None:
        return self._token

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    # -- внутреннее --------------------------------------------------------

    def _headers(self, *, auth: bool) -> dict[str, str]:
        if auth and self._token:
            return {"Authorization": f"Bearer {self._token}"}
        return {}

    async def _request(self, method, path, *, json=None, params=None, files=None, auth=True):
        try:
            resp = await self._client.request(
                method, path, json=json, params=params, files=files,
                headers=self._headers(auth=auth),
            )
        except httpx.HTTPError as exc:  # таймаут, обрыв, DNS и т.п.
            raise NetworkError(str(exc)) from exc
        if resp.status_code == 401:
            raise AuthError("unauthorized")
        if resp.status_code >= 500:
            raise NetworkError(f"server status {resp.status_code}")
        if resp.status_code >= 400:
            raise ServerError(self._error_code(resp) or f"http {resp.status_code}")
        return resp

    @staticmethod
    def _error_code(resp: httpx.Response) -> str | None:
        try:
            return resp.json().get("error")
        except Exception:
            return None

    @staticmethod
    def _json(resp: httpx.Response):
        try:
            return resp.json()
        except Exception as exc:
            raise ProtocolError("invalid json in response") from exc

    def _session_from(self, data) -> Session:
        try:
            user = data["user"]
            token = data["token"]
            sess = Session(
                server_url=self._base,
                username=user["username"],
                user_id=int(user["id"]),
                token=token,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ProtocolError("malformed auth response") from exc
        self._token = token
        return sess

    # -- публичный API -----------------------------------------------------

    async def register(self, username: str, password: str) -> Session:
        resp = await self._request(
            "POST", "/api/auth/register",
            json={"username": username, "password": password}, auth=False,
        )
        return self._session_from(self._json(resp))

    async def login(self, username: str, password: str) -> Session:
        resp = await self._request(
            "POST", "/api/auth/login",
            json={"username": username, "password": password}, auth=False,
        )
        return self._session_from(self._json(resp))

    async def logout(self) -> None:
        try:
            await self._request("POST", "/api/auth/logout")
        finally:
            self._token = None

    async def list_rooms(self) -> list[Room]:
        resp = await self._request("GET", "/api/rooms")
        data = self._json(resp)
        try:
            return [
                Room(
                    id=int(r["id"]),
                    name=r.get("name"),
                    is_direct=bool(r.get("is_direct", False)),
                    updated_at=r.get("updated_at"),
                )
                for r in data["rooms"]
            ]
        except (KeyError, TypeError, ValueError) as exc:
            raise ProtocolError("malformed rooms response") from exc

    async def create_room(self, name: str) -> Room:
        resp = await self._request("POST", "/api/rooms", json={"name": name})
        data = self._json(resp)
        try:
            return Room(
                id=int(data["id"]),
                name=data.get("name"),
                is_direct=bool(data.get("is_direct", False)),
                updated_at=data.get("updated_at"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ProtocolError("malformed room response") from exc

    async def get_messages(
        self, room_id: int, *, after: int | None = None, limit: int | None = None
    ) -> tuple[list[RemoteMessage], int | None]:
        params: dict[str, int] = {}
        if after is not None:
            params["after"] = after
        if limit is not None:
            params["limit"] = limit
        resp = await self._request(
            "GET", f"/api/rooms/{room_id}/messages", params=params or None
        )
        data = self._json(resp)
        try:
            msgs = [self._message_from(m, room_id) for m in data["messages"]]
        except (KeyError, TypeError, ValueError) as exc:
            raise ProtocolError("malformed messages response") from exc
        next_cursor = data.get("next_cursor")
        return msgs, (int(next_cursor) if next_cursor is not None else None)

    async def post_message(
        self, room_id: int, body: str, client_msg_id: str, *,
        media: str | None = None, reply_to: int | None = None,
    ) -> RemoteMessage:
        payload = {"room_id": room_id, "body": body, "client_msg_id": client_msg_id}
        if media is not None:
            payload["media"] = media
        if reply_to is not None:
            payload["reply_to"] = reply_to
        resp = await self._request("POST", "/api/messages", json=payload)
        data = self._json(resp)
        try:
            msg = self._message_from(data, room_id)
        except (KeyError, TypeError, ValueError) as exc:
            raise ProtocolError("malformed message response") from exc
        if msg.client_msg_id is None:
            msg.client_msg_id = client_msg_id
        return msg

    async def edit_message(self, message_id: int, body: str) -> None:
        """Изменить своё сообщение (по серверному id)."""
        await self._request(
            "POST", f"/api/messages/{message_id}/edit", json={"body": body}
        )

    async def delete_message(self, message_id: int) -> None:
        """Удалить своё сообщение (по серверному id)."""
        await self._request("POST", f"/api/messages/{message_id}/delete")

    async def upload_media(
        self, room_id: int, filename: str, data: bytes, mime_type: str
    ) -> dict:
        resp = await self._request(
            "POST", f"/api/rooms/{room_id}/media",
            files={"file": (filename, data, mime_type)},
        )
        payload = self._json(resp)
        try:
            return {
                "filename": payload["filename"],
                "mime_type": payload.get("mime_type"),
                "size": payload.get("size"),
            }
        except (KeyError, TypeError) as exc:
            raise ProtocolError("malformed upload response") from exc

    async def download_media(self, room_id: int, filename: str) -> tuple[bytes, str]:
        resp = await self._request("GET", f"/api/rooms/{room_id}/media/{filename}")
        return resp.content, resp.headers.get("content-type", "application/octet-stream")

    @staticmethod
    def _message_from(item: dict, room_id: int) -> RemoteMessage:
        return RemoteMessage(
            id=int(item["id"]),
            room_id=int(item.get("room_id", room_id)),
            sender=item["sender"],
            body=item["body"],
            created_at=item["created_at"],
            client_msg_id=item.get("client_msg_id"),
            media=item.get("media"),
            reply=item.get("reply_to") or None,
        )
