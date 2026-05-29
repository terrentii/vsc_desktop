"""Исключения хранилища."""


class StorageError(Exception):
    """Базовое исключение хранилища."""


class VaultExists(StorageError):
    """Vault по указанному пути уже существует."""


class WrongPassword(StorageError):
    """Неверный мастер-пароль."""


class VaultLocked(StorageError):
    """Вход временно заблокирован после неверных попыток."""

    def __init__(self, seconds_left: float):
        super().__init__(f"vault locked for {seconds_left:.0f}s")
        self.seconds_left = seconds_left


class CorruptVault(StorageError):
    """БД или sidecar повреждены/несовместимы."""
