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

    def delete(self, key: str) -> None:
        self._c.execute("DELETE FROM settings WHERE key=?", (key,))
        self._c.commit()

    def delete_prefix(self, prefix: str) -> None:
        """Удалить все ключи с данным префиксом (напр. курсоры central.cursor.*)."""
        self._c.execute("DELETE FROM settings WHERE key LIKE ?", (prefix + "%",))
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

    def get_by_room_id(self, room_id, mode: str | None = None):
        if mode is None:
            cur = self._c.execute("SELECT * FROM conversations WHERE room_id=?", (room_id,))
        else:
            cur = self._c.execute(
                "SELECT * FROM conversations WHERE room_id=? AND mode=?", (room_id, mode)
            )
        cur.row_factory = _row_factory
        return cur.fetchone()

    def list(self, mode: str | None = None):
        if mode is None:
            cur = self._c.execute("SELECT * FROM conversations ORDER BY id")
        else:
            cur = self._c.execute(
                "SELECT * FROM conversations WHERE mode=? ORDER BY id", (mode,)
            )
        cur.row_factory = _row_factory
        return cur.fetchall()

    def rename(self, conversation_id: int, title: str) -> None:
        """Локальное переименование беседы (заголовок живёт только в vault)."""
        self._c.execute(
            "UPDATE conversations SET title=? WHERE id=?", (title, conversation_id)
        )
        self._c.commit()

    def delete(self, conversation_id: int) -> None:
        """Удалить беседу (сообщения чистить отдельно — FK без каскада)."""
        self._c.execute("DELETE FROM conversations WHERE id=?", (conversation_id,))
        self._c.commit()


class MessagesRepo(_Base):
    def add(self, conversation_id, *, direction, body, status, wire_seq=None,
            client_msg_id=None, sender=None, kind="text", filename=None,
            mime_type=None, media_ref=None, timestamp=None,
            reply_author=None, reply_snippet=None) -> int:
        # timestamp — авторитетное время события (например, серверный created_at
        # «Центра»); без него берём локальные часы.
        now = timestamp if timestamp is not None else time.time()
        cur = self._c.execute(
            "INSERT INTO messages(conversation_id, direction, body, status, wire_seq,"
            " client_msg_id, sender, sent_at, received_at, kind, filename, mime_type,"
            " media_ref, reply_author, reply_snippet)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (conversation_id, direction, body, status, wire_seq, client_msg_id, sender,
             now if direction == "out" else None,
             now if direction == "in" else None,
             kind, filename, mime_type, media_ref, reply_author, reply_snippet),
        )
        self._c.commit()
        return cur.lastrowid

    def list(self, conversation_id):
        cur = self._c.execute(
            "SELECT * FROM messages WHERE conversation_id=? ORDER BY id", (conversation_id,)
        )
        cur.row_factory = _row_factory
        return cur.fetchall()

    def get(self, message_id: int):
        cur = self._c.execute("SELECT * FROM messages WHERE id=?", (message_id,))
        cur.row_factory = _row_factory
        return cur.fetchone()

    def set_status(self, message_id: int, status: str) -> None:
        self._c.execute("UPDATE messages SET status=? WHERE id=?", (status, message_id))
        self._c.commit()

    def set_body(self, message_id: int, body: bytes) -> None:
        """Бэкафилл тела после ленивой докачки вложения (см. mys_centralized.sync)."""
        self._c.execute("UPDATE messages SET body=? WHERE id=?", (body, message_id))
        self._c.commit()

    def find_by_wire(self, conversation_id, wire_seq):
        """Сообщение беседы по серверному id (live-правки/удаления «Центра»)."""
        cur = self._c.execute(
            "SELECT * FROM messages WHERE conversation_id=? AND wire_seq=? LIMIT 1",
            (conversation_id, wire_seq),
        )
        cur.row_factory = _row_factory
        return cur.fetchone()

    def delete(self, message_id: int) -> None:
        """Удалить одно сообщение (правка с сервера или своё удаление)."""
        self._c.execute("DELETE FROM messages WHERE id=?", (message_id,))
        self._c.commit()

    def exists_wire(self, conversation_id, wire_seq) -> bool:
        """Есть ли уже сообщение с данным серверным id (wire_seq) в беседе."""
        row = self._c.execute(
            "SELECT 1 FROM messages WHERE conversation_id=? AND wire_seq=? LIMIT 1",
            (conversation_id, wire_seq),
        ).fetchone()
        return row is not None

    def find_out_by_client_id(self, conversation_id, client_msg_id):
        cur = self._c.execute(
            "SELECT * FROM messages WHERE conversation_id=? AND client_msg_id=?"
            " AND direction='out'",
            (conversation_id, client_msg_id),
        )
        cur.row_factory = _row_factory
        return cur.fetchone()

    def find_unconfirmed_out_by_body(self, conversation_id, body):
        """Старейшее исходящее с таким телом, ещё не получившее серверный id.

        Нужно для дедупа собственного эха, когда сервер в WS-кадре не присылает
        ``client_msg_id``: связываем эхо с уже отправленным исходящим по телу."""
        cur = self._c.execute(
            "SELECT * FROM messages WHERE conversation_id=? AND direction='out'"
            " AND wire_seq IS NULL AND body=? ORDER BY id LIMIT 1",
            (conversation_id, body),
        )
        cur.row_factory = _row_factory
        return cur.fetchone()

    def mark_sent(self, message_id: int, *, wire_seq, status: str = "sent") -> None:
        self._c.execute(
            "UPDATE messages SET wire_seq=?, status=? WHERE id=?",
            (wire_seq, status, message_id),
        )
        self._c.commit()

    def delete_for_conversation(self, conversation_id: int) -> None:
        self._c.execute(
            "DELETE FROM messages WHERE conversation_id=?", (conversation_id,)
        )
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

    def delete(self, conversation_id: int) -> None:
        self._c.execute("DELETE FROM ratchet_state WHERE conversation_id=?", (conversation_id,))
        self._c.commit()
