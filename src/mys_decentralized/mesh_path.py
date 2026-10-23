"""Канал P2P через mesh: транспорт сессии поверх маршрута и выбор пути.

Рандеву через сервер и поиск через mesh идут параллельно. Пару от сервера оба
получают почти одновременно, поэтому сервер в приоритете: mesh нашёл первым —
ждём сервер ещё MESH_GRACE; сервер недоступен — сразу mesh (спека этапа 2).
"""

from __future__ import annotations

import asyncio

from mys_mesh.node import MeshClosed, MeshNode
from mys_mesh.tags import tag_key

from .errors import TransportError
from .protocol import Role
from .rendezvous import RendezvousClient
from .transport import RelayTransport, Transport

MESH_GRACE = 3.0


class MeshPathTransport(Transport):
    def __init__(self, t):
        self._t = t

    async def send(self, data: bytes) -> None:
        try:
            await self._t.send(data)
        except MeshClosed as exc:
            raise TransportError(str(exc)) from exc

    async def recv(self) -> bytes:
        try:
            return await self._t.recv()
        except MeshClosed as exc:
            raise TransportError(str(exc)) from exc

    async def close(self) -> None:
        await self._t.close()


async def pair(rendezvous_url: str, mesh: MeshNode | None, room_id: bytes, prs: bytes,
               wait: float, *, grace: float = MESH_GRACE):
    """→ (role, transport, path, rendezvous|None); path — "relay" или "mesh"."""
    server = asyncio.ensure_future(RendezvousClient(rendezvous_url).join(room_id, [], timeout=wait))
    if mesh is None:
        rv = await server
        return rv.role, RelayTransport.from_rendezvous(rv), "relay", rv
    found = asyncio.ensure_future(mesh.find(tag_key(prs), wait))
    loop = asyncio.get_running_loop()
    deadline: float | None = None
    errors: list[BaseException] = []
    winner = None
    try:
        pending = {server, found}
        while pending:
            timeout = None if deadline is None else max(0.0, deadline - loop.time())
            done, pending = await asyncio.wait(pending, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
            if not done:
                break  # mesh нашёл, а пара от сервера за MESH_GRACE не пришла
            if server in done:
                if server.exception() is None:
                    winner = "relay"
                    rv = server.result()
                    return rv.role, RelayTransport.from_rendezvous(rv), "relay", rv
                errors.append(server.exception())
            if found in done:
                if found.exception() is not None:
                    errors.append(found.exception())
                elif server.done():
                    break  # сервер уже не ответит — сразу mesh
                else:
                    deadline = loop.time() + grace
        if found.done() and not found.cancelled() and found.exception() is None:
            winner = "mesh"
            role, t = found.result()
            return Role(int(role)), MeshPathTransport(t), "mesh", None
        raise errors[0] if errors else TimeoutError("собеседник не найден")
    finally:
        for task in (server, found):
            if not task.done():
                task.cancel()
        # проигравший mesh-маршрут — закрыть (RERR), чтобы не висел у ретрансляторов
        if winner == "relay" and found.done() and not found.cancelled() and found.exception() is None:
            await found.result()[1].close()
