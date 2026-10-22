"""Прямой канал WebRTC (aiortc) поверх P2P-сессии — DirectLink десктопа.

Сигналинг — JSON-строки внутри E2E-сессии (``Session.send_signal``, kind
``KIND_SIGNAL``), общий с телефоном (``ru.mobile.mys.p2p.DirectLink``):

  {"t":"offer","sdp":…}  {"t":"answer","sdp":…}
  {"t":"cand","c":"candidate:…","mid":"0","idx":0}

aiortc кладёт свои кандидаты прямо в SDP (trickle не шлёт), а чужие trickle-
кандидаты принимает; пришедшие раньше удалённого SDP — буферизуются.
DataChannel ``mys``: ordered, reliable; один wire-кадр = одно бинарное сообщение.

Зависимость необязательная (``pip install .[webrtc]``): без aiortc модуль не
импортируется, и сессии остаются на relay.
"""

import asyncio
import json
from collections.abc import Callable

from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription
from aiortc.sdp import candidate_from_sdp

from .errors import TransportError
from .transport import Transport

# Сколько можно держать в буфере канала, прежде чем ждать (файл — сотни кадров).
_MAX_BUFFERED = 4 * 1024 * 1024


class DataChannelTransport(Transport):
    """Транспорт поверх открытого RTCDataChannel."""

    def __init__(self, channel):
        self._ch = channel
        self._queue: asyncio.Queue = asyncio.Queue()
        self._closed = False
        channel.on("message", self._on_message)
        channel.on("close", lambda: self._queue.put_nowait(None))

    def _on_message(self, message) -> None:
        self._queue.put_nowait(message if isinstance(message, bytes) else message.encode("utf-8"))

    async def send(self, data: bytes) -> None:
        if self._closed or self._ch.readyState != "open":
            raise TransportError("прямой канал закрыт")
        while self._ch.bufferedAmount > _MAX_BUFFERED:
            await asyncio.sleep(0.01)
        self._ch.send(data)

    async def recv(self) -> bytes:
        item = await self._queue.get()
        if item is None:
            raise TransportError("прямой канал закрыт")
        return item

    async def close(self) -> None:
        self._closed = True
        self._ch.close()
        self._queue.put_nowait(None)


class WebRtcLink:
    """Одна попытка прямого канала на сессию (offer у ответчика — новый PeerConnection)."""

    def __init__(self, ice_servers: list[str]):
        self._ice = [RTCIceServer(urls=u) for u in ice_servers]
        self._pc: RTCPeerConnection | None = None
        self._pending: list = []  # trickle-кандидаты до удалённого SDP
        self._closed_pcs: set[int] = set()

    def start(self, initiator: bool, signal: Callable[[str], None],
              opened: Callable[[Transport], None], closed: Callable[[], None]) -> None:
        self._signal, self._opened, self._closed = signal, opened, closed
        if initiator:
            asyncio.ensure_future(self._offer())

    def on_signal(self, data: str) -> None:
        asyncio.ensure_future(self._handle(json.loads(data)))

    def restart(self) -> None:
        asyncio.ensure_future(self._offer())

    def close(self) -> None:
        if self._pc is not None:
            asyncio.ensure_future(self._pc.close())
            self._pc = None

    def _new_pc(self) -> RTCPeerConnection:
        if self._pc is not None:
            asyncio.ensure_future(self._pc.close())
        pc = RTCPeerConnection(RTCConfiguration(iceServers=self._ice))
        self._pc = pc
        self._pending = []

        @pc.on("connectionstatechange")
        async def _state():
            if pc.connectionState in ("failed", "closed"):
                self._fire_closed(pc)

        return pc

    def _wire(self, pc: RTCPeerConnection, channel) -> None:
        transport = DataChannelTransport(channel)

        def on_open():
            if pc is self._pc:
                self._opened(transport)

        if channel.readyState == "open":
            on_open()
        else:
            channel.on("open", on_open)
        channel.on("close", lambda: self._fire_closed(pc))

    def _fire_closed(self, pc: RTCPeerConnection) -> None:
        """Один «closed» на попытку и только для текущего PeerConnection."""
        if id(pc) in self._closed_pcs or pc is not self._pc:
            return
        self._closed_pcs.add(id(pc))
        self._closed()

    async def _offer(self) -> None:
        pc = self._new_pc()
        self._wire(pc, pc.createDataChannel("mys", ordered=True))
        await pc.setLocalDescription(await pc.createOffer())
        self._signal(json.dumps({"t": "offer", "sdp": pc.localDescription.sdp}))

    async def _handle(self, msg: dict) -> None:
        kind = msg.get("t")
        if kind == "offer":
            pc = self._new_pc()

            @pc.on("datachannel")
            def on_dc(channel):
                self._wire(pc, channel)

            await pc.setRemoteDescription(RTCSessionDescription(sdp=msg["sdp"], type="offer"))
            await self._flush_pending(pc)
            await pc.setLocalDescription(await pc.createAnswer())
            self._signal(json.dumps({"t": "answer", "sdp": pc.localDescription.sdp}))
        elif kind == "answer" and self._pc is not None:
            await self._pc.setRemoteDescription(RTCSessionDescription(sdp=msg["sdp"], type="answer"))
            await self._flush_pending(self._pc)
        elif kind == "cand":
            line = msg.get("c") or ""
            if not line:
                return  # конец кандидатов
            cand = candidate_from_sdp(line.split(":", 1)[1] if line.startswith("candidate:") else line)
            cand.sdpMid = msg.get("mid")
            cand.sdpMLineIndex = msg.get("idx")
            pc = self._pc
            if pc is None or pc.remoteDescription is None:
                self._pending.append(cand)
            else:
                await pc.addIceCandidate(cand)

    async def _flush_pending(self, pc: RTCPeerConnection) -> None:
        pending, self._pending = self._pending, []
        for cand in pending:
            await pc.addIceCandidate(cand)
