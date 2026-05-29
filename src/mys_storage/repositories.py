"""Репозитории поверх соединения SQLCipher."""

import time

from mys_crypto import ratchet


def _row_factory(cursor, row):
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


class _Base:
    def __init__(self, conn):
        self._c = conn


class SettingsRepo(_Base):
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


class IdentitiesRepo(_Base):
    def add(self, *, kind, public_key, private_key=None, label=None, context=None) -> int:
        cur = self._c.execute(
            "INSERT INTO identities(kind, public_key, private_key, label, context, created_at)"
            " VALUES(?,?,?,?,?,?)",
            (kind, public_key, private_key, label, context, time.time()),
        )
        self._c.commit()
        return cur.lastrowid

    def get(self, identity_id: int):
        cur = self._c.execute("SELECT * FROM identities WHERE id=?", (identity_id,))
        cur.row_factory = _row_factory
        return cur.fetchone()


class ContactsRepo(_Base):
    def add(self, *, public_key, fingerprint=None, alias=None) -> int:
        cur = self._c.execute(
            "INSERT INTO contacts(public_key, fingerprint, alias, created_at)"
            " VALUES(?,?,?,?)",
            (public_key, fingerprint, alias, time.time()),
        )
        self._c.commit()
        return cur.lastrowid

    def get(self, contact_id: int):
        cur = self._c.execute("SELECT * FROM contacts WHERE id=?", (contact_id,))
        cur.row_factory = _row_factory
        return cur.fetchone()


class ConversationsRepo(_Base):
    def add(self, *, mode, peer_contact_id=None, room_id=None, title=None) -> int:
        cur = self._c.execute(
            "INSERT INTO conversations(mode, peer_contact_id, room_id, title, created_at)"
            " VALUES(?,?,?,?,?)",
            (mode, peer_contact_id, room_id, title, time.time()),
        )
        self._c.commit()
        return cur.lastrowid

    def get(self, conversation_id: int):
        cur = self._c.execute("SELECT * FROM conversations WHERE id=?", (conversation_id,))
        cur.row_factory = _row_factory
        return cur.fetchone()


class MessagesRepo(_Base):
    def add(self, conversation_id, *, direction, body, status, wire_seq=None) -> int:
        now = time.time()
        cur = self._c.execute(
            "INSERT INTO messages(conversation_id, direction, body, status, wire_seq, sent_at, received_at)"
            " VALUES(?,?,?,?,?,?,?)",
            (conversation_id, direction, body, status, wire_seq,
             now if direction == "out" else None,
             now if direction == "in" else None),
        )
        self._c.commit()
        return cur.lastrowid

    def list(self, conversation_id):
        cur = self._c.execute(
            "SELECT * FROM messages WHERE conversation_id=? ORDER BY id", (conversation_id,)
        )
        cur.row_factory = _row_factory
        return cur.fetchall()

    def set_status(self, message_id: int, status: str) -> None:
        self._c.execute("UPDATE messages SET status=? WHERE id=?", (status, message_id))
        self._c.commit()


class RatchetRepo(_Base):
    def save_state(self, conversation_id: int, state) -> None:
        blob = ratchet.serialize_state(state)
        self._c.execute(
            "INSERT INTO ratchet_state(conversation_id, state_blob, updated_at) VALUES(?,?,?)"
            " ON CONFLICT(conversation_id) DO UPDATE SET state_blob=excluded.state_blob,"
            " updated_at=excluded.updated_at",
            (conversation_id, blob, time.time()),
        )
        self._c.commit()

    def load_state(self, conversation_id: int):
        row = self._c.execute(
            "SELECT state_blob FROM ratchet_state WHERE conversation_id=?", (conversation_id,)
        ).fetchone()
        if row is None:
            return None
        return ratchet.deserialize_state(row[0])
