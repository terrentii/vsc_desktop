"""WebSocket-клиент централизованного режима (real-time приём).

Контракт §6 спеки: connect → кадр auth → `ready` → пуш `message`. Авто-реконнект
с экспоненциальным backoff и джиттером. Знает только wire-формат кадров, не знает
о хранилище/UI.
"""

from __future__ import annotations

import asyncio
import json
import random
from collections.abc import AsyncIterator

from websockets.asyncio.client import connect as ws_connect
from websockets.exceptions import ConnectionClosed

from .errors import AuthError, ProtocolError


class WsClient:
    def __init__(
        self,
        url: str,
        token: str,
        *,
        connect=None,
        ping_interval: float | None = 20.0,
        initial_backoff: float = 0.5,
        max_backoff: float = 30.0,
        jitter: float = 0.3,
    ):
        self.url = url
        self._token = token
        self._connect = connect or ws_connect
        self._ping_interval = ping_interval
        self._initial_backoff = initial_backoff
        self._max_backoff = max_backoff
        self._jitter = jitter
        self._closed = False

    def close(self) -> None:
        """Остановить реконнект-цикл (после текущей итерации)."""
        self._closed = True

    async def events(self) -> AsyncIterator[dict]:
        """Бесконечный поток событий с авто-реконнектом.

        Выдаёт `{"type":"ready"}` при каждом успешном (пере)подключении и далее
        кадры `message`. `AuthError` терминальна (неверный/истёкший токен).
        """
        backoff = self._initial_backoff
        while not self._closed:
            try:
                async for event in self._session():
                    backoff = self._initial_backoff  # рабочая сессия — сброс
                    yield event
            except AuthError:
                raise  # терминально: повторять бессмысленно
            except (ConnectionClosed, OSError):
                pass  # обрыв — уйдём в backoff ниже
            if self._closed:
                break
            await self._sleep_backoff(backoff)
            backoff = min(backoff * 2, self._max_backoff)

    async def _session(self) -> AsyncIterator[dict]:
        async with self._connect(self.url, ping_interval=self._ping_interval) as ws:
            await ws.send(json.dumps({"type": "auth", "token": self._token}))
            hello = self._parse(await ws.recv())
            mtype = hello.get("type")
            if mtype == "error":
                raise AuthError(hello.get("code") or "unauthorized")
            if mtype != "ready":
                raise ProtocolError(f"unexpected first frame: {mtype!r}")
            yield {"type": "ready"}
            async for raw in ws:
                yield self._parse(raw)

    async def _sleep_backoff(self, base: float) -> None:
        await asyncio.sleep(base + random.uniform(0, self._jitter))

    @staticmethod
    def _parse(raw) -> dict:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="strict")
        try:
            obj = json.loads(raw)
        except (ValueError, UnicodeDecodeError) as exc:
            raise ProtocolError("invalid ws frame") from exc
        if not isinstance(obj, dict):
            raise ProtocolError("ws frame is not a json object")
        return obj
