"""Жизненный цикл зашифрованного vault."""

import base64
import os
import threading
import time

import sqlcipher3

from mys_crypto import ratchet as _ratchet
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


class _LockedConnection:
    """Обёртка над соединением SQLCipher: сериализует доступ общим RLock.

    Позволяет делить одно соединение между потоком UI (чтение) и фоновым потоком
    P2P-сервиса (запись). ``check_same_thread=False`` снимает защитную проверку
    Python; корректность даёт этот замок (плюс serialized-режим самого sqlite).
    RLock реентерабелен, так что ``with conn:`` (транзакция) и вложенные
    ``execute`` внутри неё не дедлочатся.
    """

    def __init__(self, conn):
        self._conn = conn
        self._lock = threading.RLock()

    def execute(self, *args, **kwargs):
        with self._lock:
            return self._conn.execute(*args, **kwargs)

    def executescript(self, *args, **kwargs):
        with self._lock:
            return self._conn.executescript(*args, **kwargs)

    def commit(self):
        with self._lock:
            return self._conn.commit()

    def close(self):
        with self._lock:
            return self._conn.close()

    def __enter__(self):
        self._lock.acquire()
        try:
            self._conn.__enter__()
        except BaseException:
            self._lock.release()
            raise
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            return self._conn.__exit__(exc_type, exc, tb)
        finally:
            self._lock.release()

    def __getattr__(self, name):
        return getattr(self._conn, name)


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


def _wipe_files(db_path: str, meta_path: str) -> None:
    for p in (db_path, meta_path):
        if os.path.exists(p):
            with open(p, "r+b") as fh:
                length = os.fstat(fh.fileno()).st_size
                fh.write(b"\x00" * length)
                fh.flush()
                os.fsync(fh.fileno())
            os.remove(p)


def _register_failure(meta: dict, db_path: str, meta_path: str) -> None:
    meta["attempts"]["failed"] += 1
    duress = meta["duress"]
    if duress["wipe_enabled"] and meta["attempts"]["failed"] >= duress["threshold"]:
        _wipe_files(db_path, meta_path)
        return
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

    def change_password(self, old_password: bytes, new_password: bytes) -> None:
        salt = base64.b64decode(self._meta["kdf"]["salt"])
        check = kdf.derive_db_key(old_password, salt, **_kdf_kwargs(self._meta))
        if check.hex() != self._key.hex():
            check.wipe()
            raise WrongPassword()
        check.wipe()

        new_salt = os.urandom(sidecar.SALT_LEN)
        new_key = kdf.derive_db_key(new_password, new_salt, **_kdf_kwargs(self._meta))
        self._conn.execute(f"PRAGMA rekey = \"x'{new_key.hex()}'\"")
        self._meta["kdf"]["salt"] = base64.b64encode(new_salt).decode()
        sidecar.write_sidecar(self._meta_path, self._meta)
        self._key.wipe()
        self._key = new_key

    def receive_message(self, conversation_id: int, *, body: bytes, new_state, wire_seq=None) -> int:
        blob = _ratchet.serialize_state(new_state)  # сериализуем ДО транзакции (упадёт раньше записи)
        now = time.time()
        with self._conn:  # атомарно: commit при успехе, rollback при исключении
            cur = self._conn.execute(
                "INSERT INTO messages(conversation_id, direction, body, status, wire_seq, received_at)"
                " VALUES(?,?,?,?,?,?)",
                (conversation_id, "in", body, "received", wire_seq, now),
            )
            self._conn.execute(
                "INSERT INTO ratchet_state(conversation_id, state_blob, updated_at) VALUES(?,?,?)"
                " ON CONFLICT(conversation_id) DO UPDATE SET state_blob=excluded.state_blob,"
                " updated_at=excluded.updated_at",
                (conversation_id, blob, now),
            )
            return cur.lastrowid

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
    conn = sqlcipher3.connect(db_path, check_same_thread=False)
    _apply_key(conn, key)
    migrations.migrate(conn)
    sidecar.write_sidecar(meta_path, meta)
    return Vault(_LockedConnection(conn), db_path, meta, key)


def open_vault(db_path: str, password: bytes) -> Vault:
    meta_path = _meta_path(db_path)
    meta = sidecar.read_sidecar(meta_path)

    lock = meta["attempts"]["lockout_until"]
    now = time.time()
    if lock and now < lock:
        raise VaultLocked(lock - now)

    salt = base64.b64decode(meta["kdf"]["salt"])
    key = kdf.derive_db_key(password, salt, **_kdf_kwargs(meta))
    conn = sqlcipher3.connect(db_path, check_same_thread=False)
    _apply_key(conn, key)
    if not _verify(conn):
        conn.close()
        key.wipe()
        _register_failure(meta, db_path, meta_path)
        raise WrongPassword()

    meta["attempts"]["failed"] = 0
    meta["attempts"]["lockout_until"] = None
    sidecar.write_sidecar(meta_path, meta)
    return Vault(_LockedConnection(conn), db_path, meta, key)
