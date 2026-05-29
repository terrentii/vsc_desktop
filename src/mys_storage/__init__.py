"""Локальное зашифрованное хранилище МЫС Desktop."""

from .errors import (
    CorruptVault,
    StorageError,
    VaultExists,
    VaultLocked,
    WrongPassword,
)

__all__ = [
    "StorageError",
    "VaultExists",
    "WrongPassword",
    "VaultLocked",
    "CorruptVault",
]
