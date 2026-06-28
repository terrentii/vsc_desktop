"""Схема БД и список миграций (version, [statements])."""

MIGRATIONS: list[tuple[int, list[str]]] = [
    (1, [
        "CREATE TABLE settings ("
        " key TEXT PRIMARY KEY,"
        " value BLOB)",

        "CREATE TABLE identities ("
        " id INTEGER PRIMARY KEY,"
        " kind TEXT NOT NULL,"
        " public_key BLOB NOT NULL,"
        " private_key BLOB,"
        " label TEXT,"
        " context TEXT,"
        " created_at REAL NOT NULL)",

        "CREATE TABLE contacts ("
        " id INTEGER PRIMARY KEY,"
        " public_key BLOB NOT NULL,"
        " fingerprint TEXT,"
        " alias TEXT,"
        " created_at REAL NOT NULL,"
        " last_seen REAL)",

        "CREATE TABLE conversations ("
        " id INTEGER PRIMARY KEY,"
        " mode TEXT NOT NULL,"
        " peer_contact_id INTEGER REFERENCES contacts(id),"
        " room_id BLOB,"
        " title TEXT,"
        " created_at REAL NOT NULL,"
        " archived INTEGER NOT NULL DEFAULT 0)",

        "CREATE TABLE messages ("
        " id INTEGER PRIMARY KEY,"
        " conversation_id INTEGER NOT NULL REFERENCES conversations(id),"
        " direction TEXT NOT NULL,"
        " body BLOB,"
        " status TEXT NOT NULL,"
        " wire_seq INTEGER,"
        " sent_at REAL,"
        " received_at REAL)",

        "CREATE INDEX idx_messages_conv ON messages(conversation_id, id)",

        "CREATE TABLE ratchet_state ("
        " conversation_id INTEGER PRIMARY KEY REFERENCES conversations(id),"
        " state_blob BLOB NOT NULL,"
        " updated_at REAL NOT NULL)",
    ]),
    # v2 — централизованный режим (под-проект №6): идемпотентность исходящих и
    # дедуп по серверному id (wire_seq хранит серверный message.id).
    (2, [
        "ALTER TABLE messages ADD COLUMN client_msg_id TEXT",
        "CREATE INDEX idx_messages_conv_wire ON messages(conversation_id, wire_seq)",
    ]),
    # v3 — отображение сообщений (под-проект A): автор, серверное время, медиа.
    (3, [
        "ALTER TABLE messages ADD COLUMN author TEXT",
        "ALTER TABLE messages ADD COLUMN created_ts REAL",
        "ALTER TABLE messages ADD COLUMN media TEXT",
    ]),
]

TARGET_VERSION = MIGRATIONS[-1][0]
