"""Жизненный цикл зашифрованного vault."""

import base64
import os
import time

import sqlcipher3

from mys_crypto.secure import SecureBytes

from . import kdf, migrations, sidecar
from .errors import VaultExists, VaultLocked, WrongPassword
from .repositories import (
    ContactsRepo,
    ConversationsRepo,
    IdentitiesRepo,
    MessagesRepo,
    RatchetRepo,
    SettingsRepo,
)


def _meta_path(db_path: str) -> str:
    return db_path + ".meta.json"


def _kdf_kwargs(meta: dict) -> dict:
    k = meta["kdf"]
    return {
        "time_cost": k["time_cost"],
        "memory_cost": k["memory_cost"],
        "parallelism": k["parallelism"],
        "hash_len": k["hash_len"],
    }


def _apply_key(conn, key: SecureBytes) -> None:
    conn.execute(f"PRAGMA key = \"x'{key.hex()}'\"")


def _verify(conn) -> bool:
    try:
        conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
        return True
    except sqlcipher3.DatabaseError:
        return False


_LOCK_CAP = 300.0  # секунд


def _delay_for(failed: int) -> float:
    return min(2.0 ** failed, _LOCK_CAP)


def _register_failure(meta: dict, meta_path: str) -> None:
    meta["attempts"]["failed"] += 1
    meta["attempts"]["lockout_until"] = time.time() + _delay_for(meta["attempts"]["failed"])
    sidecar.write_sidecar(meta_path, meta)


class Vault:
    def __init__(self, conn, db_path: str, meta: dict, key: SecureBytes):
        self._conn = conn
        self._db_path = db_path
        self._meta_path = _meta_path(db_path)
        self._meta = meta
        self._key = key
        self.settings = SettingsRepo(conn)
        self.identities = IdentitiesRepo(conn)
        self.contacts = ContactsRepo(conn)
        self.conversations = ConversationsRepo(conn)
        self.messages = MessagesRepo(conn)
        self.ratchet = RatchetRepo(conn)

    def close(self) -> None:
        self._conn.close()
        self._key.wipe()


def create_vault(db_path: str, password: bytes, *, params: dict | None = None) -> Vault:
    meta_path = _meta_path(db_path)
    if os.path.exists(db_path) or os.path.exists(meta_path):
        raise VaultExists(db_path)
    meta = sidecar.new_sidecar(params)
    salt = base64.b64decode(meta["kdf"]["salt"])
    key = kdf.derive_db_key(password, salt, **_kdf_kwargs(meta))
    conn = sqlcipher3.connect(db_path)
    _apply_key(conn, key)
    migrations.migrate(conn)
    sidecar.write_sidecar(meta_path, meta)
    return Vault(conn, db_path, meta, key)


def open_vault(db_path: str, password: bytes) -> Vault:
    meta_path = _meta_path(db_path)
    meta = sidecar.read_sidecar(meta_path)

    lock = meta["attempts"]["lockout_until"]
    now = time.time()
    if lock and now < lock:
        raise VaultLocked(lock - now)

    salt = base64.b64decode(meta["kdf"]["salt"])
    key = kdf.derive_db_key(password, salt, **_kdf_kwargs(meta))
    conn = sqlcipher3.connect(db_path)
    _apply_key(conn, key)
    if not _verify(conn):
        conn.close()
        key.wipe()
        _register_failure(meta, meta_path)
        raise WrongPassword()

    meta["attempts"]["failed"] = 0
    meta["attempts"]["lockout_until"] = None
    sidecar.write_sidecar(meta_path, meta)
    return Vault(conn, db_path, meta, key)
