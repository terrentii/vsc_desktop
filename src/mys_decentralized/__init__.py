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
from .handshake import HandshakeResult, handshake
from .rendezvous import Rendezvous, RendezvousClient
from .rendezvous_server import RendezvousServer
from .transport import (
    DirectTransport,
    InMemoryTransport,
    RelayTransport,
    Transport,
    establish_transport,
    open_udp_endpoint,
)

__all__ = [
    "DecentralizedError",
    "PAKEError",
    "PeerUnavailable",
    "RendezvousError",
    "TransportError",
    "HandshakeResult",
    "handshake",
    "Rendezvous",
    "RendezvousClient",
    "RendezvousServer",
    "Transport",
    "InMemoryTransport",
    "RelayTransport",
    "DirectTransport",
    "establish_transport",
    "open_udp_endpoint",
]
