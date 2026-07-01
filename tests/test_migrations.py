import sqlcipher3

from mys_storage import migrations


def _conn():
    return sqlcipher3.connect(":memory:")


def test_migrate_creates_all_tables():
    conn = _conn()
    migrations.migrate(conn)
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    names = {r[0] for r in rows}
    assert {
        "settings", "identities", "contacts",
        "conversations", "messages", "ratchet_state",
    } <= names


def test_migrate_sets_user_version():
    conn = _conn()
    migrations.migrate(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == migrations.TARGET_VERSION


def test_migrate_is_idempotent():
    conn = _conn()
    migrations.migrate(conn)
    migrations.migrate(conn)  # повторный запуск не падает и не дублирует
    count = conn.execute(
        "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='messages'"
    ).fetchone()[0]
    assert count == 1


def test_migrate_adds_file_columns_to_messages():
    conn = _conn()
    migrations.migrate(conn)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(messages)").fetchall()}
    assert {"kind", "filename", "mime_type"} <= cols
