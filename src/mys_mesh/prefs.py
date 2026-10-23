"""Настройки mesh в зашифрованном vault: вкл., ретрансляция, свои узлы, выученные адреса."""

from __future__ import annotations

from dataclasses import dataclass, field

K_ENABLED, K_RELAY, K_NODES, K_PEERS = "mesh.enabled", "mesh.relay", "mesh.nodes", "mesh.peers"


@dataclass
class MeshPrefs:
    enabled: bool = True   # открытая сеть по умолчанию (решение владельца)
    relay: bool = True
    nodes: list[str] = field(default_factory=list)   # свои адреса узлов
    peers: list[str] = field(default_factory=list)   # выученные из PEERS


def _get(vault, key: str) -> str | None:
    raw = vault.settings.get(key)
    return raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw


def _lines(text: str | None) -> list[str]:
    return [x.strip() for x in (text or "").replace(",", "\n").split() if x.strip()]


def load(vault) -> MeshPrefs:
    return MeshPrefs(
        enabled=_get(vault, K_ENABLED) != "0",
        relay=_get(vault, K_RELAY) != "0",
        nodes=_lines(_get(vault, K_NODES)),
        peers=_lines(_get(vault, K_PEERS)),
    )


def save(vault, prefs: MeshPrefs) -> None:
    vault.settings.set(K_ENABLED, "1" if prefs.enabled else "0")
    vault.settings.set(K_RELAY, "1" if prefs.relay else "0")
    vault.settings.set(K_NODES, "\n".join(prefs.nodes))


def save_peers(vault, urls: list[str]) -> None:
    vault.settings.set(K_PEERS, "\n".join(urls[:32]))
