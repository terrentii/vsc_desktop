"""Контроллер приложения: единая точка состояния сессии поверх mys_storage.

Не импортирует Qt — тестируется изолированно. Колбэки централизованного сервиса
приходят из его фонового потока; контроллер лишь раздаёт их зарегистрированным
наблюдателям (UI-слой маршалит их в Qt-сигналы — граница CLAUDE.md).
"""

import os

from mys_storage import create_vault, open_vault
from mys_storage.vault import Vault

from . import paths

DECENTRALIZED = "decentralized"
CENTRALIZED = "centralized"


class AppController:
    def __init__(
        self,
        vault_path: str | None = None,
        *,
        kdf_params: dict | None = None,
        central_factory=None,
    ):
        self._path = vault_path or paths.default_vault_path()
        self._kdf = kdf_params
        self.vault: Vault | None = None
        self.mode: str = DECENTRALIZED
        # P2P-сервис (mys_decentralized.P2PService) подключается извне; без него
        # децентрализованный режим работает как локальная заглушка (нет сети).
        self._service = None
        # Централизованный сервис создаётся лениво при первом входе фабрикой
        # central_factory(vault, *, on_message, on_state_change, on_error).
        self._central_factory = central_factory
        self._central = None
        self._central_observers: list[dict] = []

    def attach_service(self, service) -> None:
        """Подключить P2P-сервис для децентрализованного режима."""
        self._service = service

    # --- vault ----------------------------------------------------------------

    def vault_exists(self) -> bool:
        return os.path.exists(self._path)

    def create_vault(self, password: bytes) -> None:
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        self.vault = create_vault(self._path, password, params=self._kdf)

    def unlock(self, password: bytes) -> None:
        # raises WrongPassword / VaultLocked
        self.vault = open_vault(self._path, password)

    def lock(self) -> None:
        if self._central is not None:
            self._central.stop()  # остановить фоновый loop до закрытия vault
            self._central = None
        if self.vault is not None:
            self.vault.close()
            self.vault = None

    def set_mode(self, mode: str) -> None:
        self.mode = mode

    # --- беседы и сообщения ----------------------------------------------------

    def list_conversations(self) -> list[dict]:
        return self.vault.conversations.list(self.mode)

    def create_conversation(self, title: str, *, room_phrase: str | None = None) -> int:
        # В децентрализованном режиме с фразой и подключённым сервисом — реальная
        # P2P-сессия (фраза → PAKE → канал); беседа создаётся/находится по room_id.
        # Иначе (нет сети/фразы) — локальная заглушка.
        if self.mode == DECENTRALIZED and room_phrase and self._service is not None:
            return self._service.start_session(room_phrase)
        return self.vault.conversations.add(mode=self.mode, title=title)

    def list_messages(self, conversation_id: int) -> list[dict]:
        return self.vault.messages.list(conversation_id)

    def send_message(self, conversation_id: int, text: str) -> int | None:
        # Централизованный режим с активной сессией — через сервис (он персистит).
        if (
            self.mode == CENTRALIZED
            and self._central is not None
            and self._central.session is not None
        ):
            self._central.send_message(conversation_id, text)
            return None
        # Активная P2P-сессия — отправляем через сервис (он же персистит исходящее).
        if self._service is not None and self._service.has_session(conversation_id):
            self._service.send(conversation_id, text)
            return None
        # Иначе (нет сети) — сохраняем исходящее локально.
        return self.vault.messages.add(
            conversation_id, direction="out", body=text.encode("utf-8"), status="local"
        )

    def change_password(self, old: bytes, new: bytes) -> None:
        self.vault.change_password(old, new)

    # --- централизованный режим ------------------------------------------------

    def add_central_observer(
        self, *, on_message=None, on_state_change=None, on_error=None
    ) -> None:
        """Подписаться на события централизованного сервиса (UI маршалит в Qt)."""
        self._central_observers.append(
            {"message": on_message, "state": on_state_change, "error": on_error}
        )

    def _ensure_central(self):
        if self._central is None:
            if self._central_factory is None:
                raise RuntimeError("централизованный сервис не сконфигурирован")
            self._central = self._central_factory(
                self.vault,
                on_message=self._central_on_message,
                on_state_change=self._central_on_state,
                on_error=self._central_on_error,
            )
            self._central.start()
        return self._central

    def _notify(self, key: str, *args) -> None:
        for obs in self._central_observers:
            cb = obs.get(key)
            if cb is not None:
                cb(*args)

    def _central_on_message(self, conversation_id: int, local_id: int) -> None:
        self._notify("message", conversation_id, local_id)

    def _central_on_state(self, state: str) -> None:
        self._notify("state", state)

    def _central_on_error(self, exc: Exception) -> None:
        self._notify("error", exc)

    def central_available(self) -> bool:
        """Сконфигурирован ли централизованный сервис (есть фабрика)."""
        return self._central_factory is not None

    def central_session(self):
        return self._central.session if self._central is not None else None

    def central_login(self, server_url, username, password, *, register=False):
        return self._ensure_central().login(
            server_url, username, password, register=register
        )

    def central_resume(self):
        """Восстановить сохранённую сессию (если есть) → синк → live."""
        if self.vault is None or self._central_factory is None:
            return None
        return self._ensure_central().resume()

    def central_send(self, conversation_id: int, text: str):
        return self._ensure_central().send_message(conversation_id, text)

    def central_logout(self) -> None:
        if self._central is not None:
            self._central.logout()
