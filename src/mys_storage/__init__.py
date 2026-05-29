"""Локальное зашифрованное хранилище МЫС Desktop."""

from .errors import (
    CorruptVault,
    StorageError,
    VaultExists,
    VaultLocked,
    WrongPassword,
)
from .vault import Vault, create_vault, open_vault

__all__ = [
    "Vault",
    "create_vault",
    "open_vault",
    "StorageError",
    "VaultExists",
    "WrongPassword",
    "VaultLocked",
    "CorruptVault",
]
