"""Пути приложения (XDG)."""

import os


def data_dir() -> str:
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "mys")


def default_vault_path() -> str:
    return os.path.join(data_dir(), "vault.db")
