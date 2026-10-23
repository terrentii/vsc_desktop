"""Раннер миграций по PRAGMA user_version."""

import re

from .schema import MIGRATIONS, TARGET_VERSION

__all__ = ["migrate", "TARGET_VERSION"]

_ADD_COLUMN = re.compile(r"ALTER TABLE (\w+) ADD COLUMN (\w+) ", re.IGNORECASE)


def migrate(conn) -> None:
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    for version, statements in MIGRATIONS:
        if version > current:
            for stmt in statements:
                conn.execute(stmt)
            conn.execute(f"PRAGMA user_version = {version}")
            current = version
    _add_missing_columns(conn)
    conn.commit()


def _add_missing_columns(conn) -> None:
    """Докинуть колонки, которые история миграций добавляет, а в базе их нет.

    Номера версий однажды разошлись: v3 старой ветки feat/message-display
    добавляла author/created_ts/media, а v3 main — sender. Хранилище оттуда
    помечено user_version=3, и main пропустил бы свою v3. Колонки только
    добавляются — данные и чужие колонки не трогаем.
    """
    existing: dict[str, set[str]] = {}
    for _version, statements in MIGRATIONS:
        for stmt in statements:
            m = _ADD_COLUMN.match(stmt)
            if not m:
                continue
            table, column = m.group(1), m.group(2)
            if table not in existing:
                existing[table] = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
            if column not in existing[table]:
                conn.execute(stmt)
                existing[table].add(column)
