"""Децентрализованный модуль МЫС Desktop (P2P-чат 1:1, только онлайн).

Публичный API наполняется по мере готовности под-проекта №4.
"""

from .errors import (
    DecentralizedError,
    PAKEError,
    PeerUnavailable,
    RendezvousError,
    TransportError,
)

__all__ = [
    "DecentralizedError",
    "PAKEError",
    "PeerUnavailable",
    "RendezvousError",
    "TransportError",
]
