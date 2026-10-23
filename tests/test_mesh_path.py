"""Выбор пути канала: сервер недоступен → mesh; сервер есть → сервер (этап 2)."""

import asyncio

from mys_decentralized import P2PService, RendezvousServer
from mys_mesh.internet import MeshInternet
from mys_mesh.node import MeshConfig, MeshNode
from mys_mesh.wire import TcpWire
from mys_storage import create_vault

FAST = {"time_cost": 1, "memory_cost": 8, "parallelism": 1}
PHRASE = "северный ветер сорок один"


async def _hub():
    """Публичный mesh-узел на loop теста (как демон на сервере)."""
    hub = MeshNode(MeshConfig(rreq_retry=0.3, sweep=0.3))
    server = await asyncio.start_server(lambda r, w: hub.serve(TcpWire(r, w)), "127.0.0.1", 0)
    return hub, server, server.sockets[0].getsockname()[1]


def _mesh_factory(port):
    def make():
        node = MeshNode(MeshConfig(rreq_retry=0.3, sweep=0.3))
        net = MeshInternet(node, lambda: [f"tcp:{port}"], tick=0.05,
                           connect=lambda _u: TcpWire.connect("127.0.0.1", port))
        return node, net
    return make


async def _pair_of_services(tmp_path, rendezvous_url, port, states):
    services, recv = [], {"a": [], "b": []}
    for name in ("a", "b"):
        vault = create_vault(str(tmp_path / f"{name}.db"), f"pw-{name}".encode(), params=FAST)
        svc = P2PService(
            vault, rendezvous_url, connect_timeout=15, mesh_factory=_mesh_factory(port),
            on_message=lambda _c, body, n=name: recv[n].append(body),
            on_state_change=lambda _c, st, n=name: states.setdefault(n, []).append(st),
        )
        svc.start()
        services.append(svc)
    return services, recv


async def _wait(pred, timeout=15.0):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while loop.time() < end:
        if pred():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("условие не выполнено")


async def test_server_down_channel_goes_through_mesh(tmp_path):
    hub, srv, port = await _hub()
    states: dict = {}
    (sa, sb), recv = await _pair_of_services(tmp_path, "ws://127.0.0.1:1/p2p", port, states)
    try:
        await _wait(lambda: sa.mesh_stats()["nodes"] and sb.mesh_stats()["nodes"])
        ca, cb = await asyncio.gather(asyncio.to_thread(sa.start_session, PHRASE),
                                      asyncio.to_thread(sb.start_session, PHRASE))
        assert "mesh" in states["a"] and "mesh" in states["b"]
        await asyncio.to_thread(sa.send, ca, "через mesh")
        await _wait(lambda: recv["b"])
        assert hub.stats()["relayed_bytes"] > 0
    finally:
        await asyncio.gather(asyncio.to_thread(sa.stop), asyncio.to_thread(sb.stop))
        srv.close()
        await hub.close()


async def test_server_up_wins_over_mesh(tmp_path):
    hub, srv, port = await _hub()
    rendezvous = RendezvousServer()
    host, rport = await rendezvous.start("127.0.0.1", 0)
    states: dict = {}
    (sa, sb), recv = await _pair_of_services(tmp_path, f"ws://{host}:{rport}/p2p", port, states)
    try:
        await _wait(lambda: sa.mesh_stats()["nodes"] and sb.mesh_stats()["nodes"])
        ca, cb = await asyncio.gather(asyncio.to_thread(sa.start_session, PHRASE),
                                      asyncio.to_thread(sb.start_session, PHRASE))
        assert "mesh" not in states["a"] and "mesh" not in states["b"]
        await asyncio.to_thread(sb.send, cb, "через сервер")
        await _wait(lambda: recv["a"])
        await asyncio.sleep(0.5)
        assert hub.stats()["routes"] == 0  # проигравший mesh-маршрут закрыт
    finally:
        await asyncio.gather(asyncio.to_thread(sa.stop), asyncio.to_thread(sb.stop))
        await rendezvous.stop()
        srv.close()
        await hub.close()
