"""Контроллер приложения: единая точка состояния сессии поверх mys_storage.

Не импортирует Qt — тестируется изолированно.
"""

import os

from mys_storage import create_vault, open_vault
from mys_storage.vault import Vault

from . import paths

DECENTRALIZED = "decentralized"
CENTRALIZED = "centralized"


class AppController:
    def __init__(self, vault_path: str | None = None, *, kdf_params: dict | None = None):
        self._path = vault_path or paths.default_vault_path()
        self._kdf = kdf_params
        self.vault: Vault | None = None
        self.mode: str = DECENTRALIZED

    def vault_exists(self) -> bool:
        return os.path.exists(self._path)

    def create_vault(self, password: bytes) -> None:
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        self.vault = create_vault(self._path, password, params=self._kdf)

    def unlock(self, password: bytes) -> None:
        # raises WrongPassword / VaultLocked
        self.vault = open_vault(self._path, password)

    def lock(self) -> None:
        if self.vault is not None:
            self.vault.close()
            self.vault = None

    def set_mode(self, mode: str) -> None:
        self.mode = mode

    def list_conversations(self) -> list[dict]:
        return self.vault.conversations.list(self.mode)

    def create_conversation(self, title: str, *, room_phrase: str | None = None) -> int:
        # room_phrase пока не используется (PAKE — под-проект №4); диалог создаётся локально
        return self.vault.conversations.add(mode=self.mode, title=title)

    def list_messages(self, conversation_id: int) -> list[dict]:
        return self.vault.messages.list(conversation_id)

    def send_message(self, conversation_id: int, text: str) -> int:
        # сеть не подключена (№4/№6) — сохраняем исходящее локально
        return self.vault.messages.add(
            conversation_id, direction="out", body=text.encode("utf-8"), status="local"
        )

    def change_password(self, old: bytes, new: bytes) -> None:
        self.vault.change_password(old, new)
