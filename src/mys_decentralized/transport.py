"""Транспорт: доставка непрозрачных кадров пиру.

Граница CLAUDE.md: транспорт ничего не знает о шифровании — он переносит
непрозрачные ``bytes`` (готовые wire-сообщения из :mod:`.protocol`) от одного
пира к другому. Слои ``handshake``/``session`` кладут поверх CPace/ratchet/AEAD.

Здесь: ABC ``Transport`` и in-memory дуплекс-пара для тестов/локальной склейки.
Сетевые ``RelayTransport``/``DirectTransport`` и выбор пути — далее (Task 5).
"""

import asyncio
from abc import ABC, abstractmethod


class Transport(ABC):
    """Двунаправленный канал непрозрачных кадров к одному пиру."""

    @abstractmethod
    async def send(self, data: bytes) -> None:
        """Отправить один непрозрачный кадр пиру."""

    @abstractmethod
    async def recv(self) -> bytes:
        """Получить один непрозрачный кадр от пира (ждёт при необходимости)."""

    @abstractmethod
    async def close(self) -> None:
        """Закрыть канал; последующие ``recv`` поднимают ``TransportError``."""


class InMemoryTransport(Transport):
    """Транспорт поверх двух ``asyncio.Queue`` — без сети.

    Используется в тестах хендшейка/сессии и как образец семантики: ``send``
    кладёт кадр во входящую очередь пира, ``recv`` снимает со своей. Создавать
    через :meth:`connected_pair`.
    """

    def __init__(self, inbound: asyncio.Queue, outbound: asyncio.Queue):
        self._inbound = inbound
        self._outbound = outbound
        self._closed = False

    @classmethod
    def connected_pair(cls) -> tuple["InMemoryTransport", "InMemoryTransport"]:
        a_to_b: asyncio.Queue = asyncio.Queue()
        b_to_a: asyncio.Queue = asyncio.Queue()
        a = cls(inbound=b_to_a, outbound=a_to_b)
        b = cls(inbound=a_to_b, outbound=b_to_a)
        return a, b

    async def send(self, data: bytes) -> None:
        from .errors import TransportError

        if self._closed:
            raise TransportError("send в закрытый транспорт")
        await self._outbound.put(data)

    async def recv(self) -> bytes:
        from .errors import TransportError

        item = await self._inbound.get()
        if item is _CLOSED:
            raise TransportError("транспорт закрыт")
        return item

    async def close(self) -> None:
        self._closed = True
        await self._outbound.put(_CLOSED)


_CLOSED = object()  # сентинел «канал закрыт» во входящей очереди
