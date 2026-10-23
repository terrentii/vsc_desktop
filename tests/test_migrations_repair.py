"""Хранилище от старой ветки feat/message-display: её v3 добавляла author/created_ts/
media, а v3 в main — sender. Такая база помечена user_version=3, и main применил бы
только v4+ — без sender, которую пишет репозиторий сообщений. Раннер миграций
обязан докинуть недостающие колонки, не трогая данные."""

import sqlite3

from mys_storage.migrations import migrate
from mys_storage.schema import MIGRATIONS


def _old_branch_db(path):
    conn = sqlite3.connect(path)
    for version, statements in MIGRATIONS:
        if version > 2:
            break
        for stmt in statements:
            conn.execute(stmt)
    # v3 старой ветки
    conn.execute("ALTER TABLE messages ADD COLUMN author TEXT")
    conn.execute("ALTER TABLE messages ADD COLUMN created_ts REAL")
    conn.execute("ALTER TABLE messages ADD COLUMN media TEXT")
    conn.execute("PRAGMA user_version = 3")
    conn.execute("INSERT INTO conversations(mode, created_at) VALUES('decentralized', 0)")
    conn.execute("INSERT INTO messages(conversation_id, direction, body, status) VALUES(1, 'in', x'6869', 'received')")
    conn.commit()
    return conn


def _columns(conn, table):
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def test_old_branch_vault_gets_missing_columns_and_keeps_data(tmp_path):
    conn = _old_branch_db(str(tmp_path / "old.db"))
    migrate(conn)
    msgs = _columns(conn, "messages")
    assert {"sender", "kind", "filename", "mime_type", "media_ref", "reply_author", "reply_snippet"} <= msgs
    assert {"author", "created_ts", "media"} <= msgs  # старые колонки не трогаем
    assert "p2p_prs" in _columns(conn, "conversations")
    assert conn.execute("SELECT body, kind FROM messages").fetchone() == (b"hi", "text")
    conn.execute("INSERT INTO messages(conversation_id, direction, body, status, sender) VALUES(1, 'out', x'00', 'sent', 'я')")


def test_migrate_is_idempotent(tmp_path):
    conn = _old_branch_db(str(tmp_path / "old.db"))
    migrate(conn)
    migrate(conn)
