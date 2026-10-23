"""Интернет-связь mesh: держать линки к публичным узлам (wss://…/mesh).

Телефоны и обычные десктопы входящих не принимают (NAT), поэтому интернет-mesh
строится вокруг публичных узлов: стартовые адреса из настроек + выученные из PEERS.
"""

from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable

from .node import MeshNode
from .wire import Wire, WsWire

LINKS = 3                   # одновременных линков к публичным узлам
BACKOFF = (2.0, 120.0)      # пауза перед повтором: от 2 с, удваивается до 2 мин


class MeshInternet:
    def __init__(
        self,
        node: MeshNode,
        bootstrap: Callable[[], list[str]],
        *,
        links: int = LINKS,
        connect: Callable[[str], Awaitable[Wire]] = WsWire.connect,
        tick: float = 1.0,
    ):
        self._node = node
        self._bootstrap = bootstrap
        self._links = links
        self._connect = connect
        self._tick = tick
        self._active: dict[str, asyncio.Task] = {}
        self._up: set[str] = set()
        self._fails: dict[str, int] = {}
        self._retry_at: dict[str, float] = {}
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        tasks = [t for t in (self._task, *self._active.values()) if t is not None]
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._task = None
        self._active.clear()
        self._up.clear()

    def connected(self) -> list[str]:
        """Адреса узлов, с которыми линк сейчас поднят."""
        return sorted(self._up)

    def candidates(self) -> list[str]:
        return list(dict.fromkeys([*self._bootstrap(), *self._node.known_urls]))

    async def _run(self) -> None:
        while True:
            now = time.monotonic()
            for url in self.candidates():
                if len(self._active) >= self._links:
                    break
                if url in self._active or now < self._retry_at.get(url, 0.0):
                    continue
                self._active[url] = asyncio.create_task(self._hold(url))
            await asyncio.sleep(self._tick)

    async def _hold(self, url: str) -> None:
        try:
            wire = await self._connect(url)
            self._fails.pop(url, None)
            self._up.add(url)
            await self._node.serve(wire)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass  # отказ, обрыв, неверный линк — повтор после паузы
        finally:
            self._up.discard(url)
            self._active.pop(url, None)
            n = self._fails.get(url, 0) + 1
            self._fails[url] = n
            self._retry_at[url] = time.monotonic() + min(BACKOFF[1], BACKOFF[0] * 2 ** (n - 1))
