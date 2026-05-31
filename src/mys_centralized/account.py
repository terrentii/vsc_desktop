"""Персист сессии аккаунта в зашифрованном vault (settings).

Токен чувствителен, но vault зашифрован — на диск он попадает только здесь.
В памяти держать токен в SecureBytes — follow-up (Session держит str для заголовка
Authorization).
"""

from __future__ import annotations

from .models import Session

K_SERVER = "central.server_url"
K_USER = "central.username"
K_UID = "central.user_id"
K_TOKEN = "central.token"
K_WIPE = "central.wipe_on_logout"

# Беседы централизованного режима (см. sync.MODE) и префикс ключей-курсоров.
_MODE = "centralized"
_CURSOR_PREFIX = "central.cursor."


def _dec(v):
    if v is None:
        return None
    return v.decode("utf-8") if isinstance(v, bytes) else v


def save_session(vault, sess: Session) -> None:
    s = vault.settings
    s.set(K_SERVER, sess.server_url.encode("utf-8"))
    s.set(K_USER, sess.username.encode("utf-8"))
    s.set(K_UID, str(sess.user_id).encode("utf-8"))
    s.set(K_TOKEN, sess.token.encode("utf-8"))


def load_session(vault) -> Session | None:
    s = vault.settings
    token = s.get(K_TOKEN)
    if not token:
        return None
    return Session(
        server_url=_dec(s.get(K_SERVER)),
        username=_dec(s.get(K_USER)),
        user_id=int(_dec(s.get(K_UID))),
        token=_dec(token),
    )


def clear_session(vault) -> None:
    for k in (K_SERVER, K_USER, K_UID, K_TOKEN):
        vault.settings.set(k, None)


def load_wipe_on_logout(vault) -> bool:
    """Настройка: стирать ли локальный кэш «Центра» при выходе (по умолчанию нет)."""
    return _dec(vault.settings.get(K_WIPE)) == "1"


def save_wipe_on_logout(vault, value: bool) -> None:
    vault.settings.set(K_WIPE, b"1" if value else b"0")


def wipe_local_cache(vault) -> None:
    """Стереть локальный кэш централизованного режима: беседы, их сообщения и
    курсоры синка. Сессию чистит ``clear_session`` отдельно; настройки (в т.ч.
    сам флаг wipe-on-logout) не трогаем."""
    for conv in vault.conversations.list(mode=_MODE):
        vault.messages.delete_for_conversation(conv["id"])
        vault.conversations.delete(conv["id"])
    vault.settings.delete_prefix(_CURSOR_PREFIX)
