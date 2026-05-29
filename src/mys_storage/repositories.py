"""Репозитории поверх соединения SQLCipher."""


class SettingsRepo:
    def __init__(self, conn):
        self._c = conn

    def get(self, key: str, default=None):
        row = self._c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set(self, key: str, value) -> None:
        self._c.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self._c.commit()


class IdentitiesRepo:
    def __init__(self, conn):
        self._c = conn


class ContactsRepo:
    def __init__(self, conn):
        self._c = conn


class ConversationsRepo:
    def __init__(self, conn):
        self._c = conn


class MessagesRepo:
    def __init__(self, conn):
        self._c = conn


class RatchetRepo:
    def __init__(self, conn):
        self._c = conn
