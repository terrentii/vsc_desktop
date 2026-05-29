"""Раннер миграций по PRAGMA user_version."""

from .schema import MIGRATIONS, TARGET_VERSION

__all__ = ["migrate", "TARGET_VERSION"]


def migrate(conn) -> None:
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    for version, statements in MIGRATIONS:
        if version > current:
            for stmt in statements:
                conn.execute(stmt)
            conn.execute(f"PRAGMA user_version = {version}")
            current = version
    conn.commit()
