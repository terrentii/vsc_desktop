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
    # v3 — имя отправителя входящих сообщений (централизованный режим,
    # многопользовательские комнаты): сервер отдаёт его в RemoteMessage.sender.
    (3, [
        "ALTER TABLE messages ADD COLUMN sender TEXT",
    ]),
    # v4 — файлы в P2P: тип сообщения и метаданные вложения.
    (4, [
        "ALTER TABLE messages ADD COLUMN kind TEXT NOT NULL DEFAULT 'text'",
        "ALTER TABLE messages ADD COLUMN filename TEXT",
        "ALTER TABLE messages ADD COLUMN mime_type TEXT",
    ]),
    # v5 — изображения/файлы в «Центре»: ссылка на серверное имя вложения
    # (kind='image' наравне с 'text'/'file' из v4 — доп. колонка не нужна).
    (5, [
        "ALTER TABLE messages ADD COLUMN media_ref TEXT",
    ]),
    # v6 — ответы в «Центре»: денормализованная цитата (автор + первые 60 симв.)
    # — сервер отдаёт её готовой, локально ссылку не резолвим (веб хранит
    # reply_to хрупким индексом, паритет по отображению, не по хранению).
    (6, [
        "ALTER TABLE messages ADD COLUMN reply_author TEXT",
        "ALTER TABLE messages ADD COLUMN reply_snippet TEXT",
    ]),
]

TARGET_VERSION = MIGRATIONS[-1][0]
