# Локальное хранилище (mys_storage) — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Реализовать зашифрованное локальное хранилище `mys_storage` (SQLCipher) и закрыть два follow-up'а крипто-ядра: глобальный кап `mkskipped` и зануление ключей (`SecureBytes`). Спецификация: `docs/superpowers/specs/2026-05-29-local-storage.md`.

**Architecture:** Зашифрованная целиком SQLCipher-БД + открытый sidecar с несекретными KDF-параметрами и счётчиками попыток. Ключ БД выводится Argon2id из мастер-пароля и подаётся в SQLCipher сырым (hex, без второго KDF). Хранилище персистит непрозрачные байты — сериализацию состояния ratchet даёт крипто-ядро. Границы строгие: хранилище не знает крипто-внутренностей, крипто не знает о БД.

**Tech Stack:** Python 3.13, `sqlcipher3-binary>=0.6` (вшитый SQLCipher 4), `mys_crypto`, `cryptography`, `argon2-cffi`, `pytest`.

---

## Структура файлов

```
src/mys_crypto/
  secure.py        # НОВОЕ: SecureBytes (bytearray + wipe)
  ratchet.py       # МОДИФ: serialize_state/deserialize_state, MAX_SKIP_SESSION + вытеснение
src/mys_storage/
  __init__.py      # публичный API
  errors.py        # WrongPassword, VaultLocked, VaultExists, CorruptVault
  sidecar.py       # открытый .meta.json: соль, параметры Argon2id, попытки, duress
  kdf.py           # derive_db_key: пароль+соль -> SecureBytes
  schema.py        # MIGRATIONS (CREATE TABLE ...)
  migrations.py    # раннер по PRAGMA user_version
  repositories.py  # settings, identities, contacts, conversations, messages, ratchet
  vault.py         # create/open/rekey/transaction/close, лимит попыток, duress
tests/
  test_secure.py
  test_ratchet_persistence.py
  test_sidecar.py
  test_migrations.py
  test_vault.py
  test_repositories.py
  test_storage_integration.py
```

**Зоны ответственности:** `secure` — нижний слой памяти. `ratchet` использует `secure`/`primitives`, не знает о БД. `mys_storage.*` не знает крипто-внутренностей (хранит `bytes` от `serialize_state`). `vault` оркестрирует sidecar+kdf+migrations+repositories.

---

### Task 1: Каркас mys_storage и зависимость sqlcipher3

**Files:**
- Modify: `pyproject.toml`
- Create: `src/mys_storage/__init__.py`
- Create: `src/mys_storage/errors.py`

- [ ] **Step 1: Добавить зависимость в `pyproject.toml`**

В секцию `dependencies` добавить:
```toml
    "sqlcipher3-binary>=0.6",
```

- [ ] **Step 2: Создать `src/mys_storage/errors.py`**

```python
"""Исключения хранилища."""


class StorageError(Exception):
    """Базовое исключение хранилища."""


class VaultExists(StorageError):
    """Vault по указанному пути уже существует."""


class WrongPassword(StorageError):
    """Неверный мастер-пароль."""


class VaultLocked(StorageError):
    """Вход временно заблокирован после неверных попыток."""

    def __init__(self, seconds_left: float):
        super().__init__(f"vault locked for {seconds_left:.0f}s")
        self.seconds_left = seconds_left


class CorruptVault(StorageError):
    """БД или sidecar повреждены/несовместимы."""
```

- [ ] **Step 3: Создать `src/mys_storage/__init__.py`** (API дополним в Task 12)

```python
"""Локальное зашифрованное хранилище МЫС Desktop."""

from .errors import (
    CorruptVault,
    StorageError,
    VaultExists,
    VaultLocked,
    WrongPassword,
)

__all__ = [
    "StorageError",
    "VaultExists",
    "WrongPassword",
    "VaultLocked",
    "CorruptVault",
]
```

- [ ] **Step 4: Установить зависимость**

Run: `.venv/bin/pip install "sqlcipher3-binary>=0.6"`
Expected: успешная установка wheel.

- [ ] **Step 5: Проверить импорт sqlcipher3 и шифрование**

Run:
```
.venv/bin/python -c "import sqlcipher3; c=sqlcipher3.connect(':memory:'); c.execute(\"PRAGMA key=\\\"x'$(python -c 'print(\"00\"*32)')'\\\"\"); c.execute('CREATE TABLE t(x)'); print('ok')"
```
Expected: `ok` (SQLCipher работает с сырым hex-ключом).

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/mys_storage/__init__.py src/mys_storage/errors.py
git commit -m "chore: scaffold mys_storage package and sqlcipher3 dep"
```

---

### Task 2: SecureBytes (зануление ключей) — крипто-ядро

**Files:**
- Create: `src/mys_crypto/secure.py`
- Test: `tests/test_secure.py`

- [ ] **Step 1: Написать падающий тест**

`tests/test_secure.py`:
```python
from mys_crypto.secure import SecureBytes


def test_holds_and_exposes_bytes():
    sb = SecureBytes(b"\x01\x02\x03")
    assert bytes(sb) == b"\x01\x02\x03"
    assert len(sb) == 3
    assert sb.hex() == "010203"


def test_wipe_zeroizes():
    sb = SecureBytes(b"secret-key-material")
    sb.wipe()
    assert bytes(sb) == bytes(len(b"secret-key-material"))


def test_context_manager_wipes_on_exit():
    with SecureBytes(b"\xaa" * 32) as sb:
        assert bytes(sb) != bytes(32)
    assert bytes(sb) == bytes(32)
```

- [ ] **Step 2: Запустить, убедиться что падает**

Run: `.venv/bin/pytest tests/test_secure.py -v`
Expected: FAIL — `ModuleNotFoundError: mys_crypto.secure`.

- [ ] **Step 3: Реализация**

`src/mys_crypto/secure.py`:
```python
"""Best-effort зануление ключевого материала в памяти.

Ограничение: исходные `bytes` в Python иммутабельны и могут копироваться GC —
гарантия зануления не абсолютная. SecureBytes снижает время жизни ключей в
изменяемом буфере и затирает его явно.
"""


class SecureBytes:
    def __init__(self, data: bytes | bytearray):
        self._buf = bytearray(data)

    def __bytes__(self) -> bytes:
        return bytes(self._buf)

    def __len__(self) -> int:
        return len(self._buf)

    def hex(self) -> str:
        return self._buf.hex()

    def wipe(self) -> None:
        for i in range(len(self._buf)):
            self._buf[i] = 0

    def __enter__(self) -> "SecureBytes":
        return self

    def __exit__(self, *exc) -> None:
        self.wipe()
```

- [ ] **Step 4: Запустить, убедиться что проходит**

Run: `.venv/bin/pytest tests/test_secure.py -v`
Expected: PASS (3 теста).

- [ ] **Step 5: Commit**

```bash
git add src/mys_crypto/secure.py tests/test_secure.py
git commit -m "feat: add SecureBytes for best-effort key zeroization"
```

---

### Task 3: Сериализация состояния ratchet — крипто-ядро

**Files:**
- Modify: `src/mys_crypto/ratchet.py`
- Test: `tests/test_ratchet_persistence.py`

- [ ] **Step 1: Написать падающий тест**

`tests/test_ratchet_persistence.py`:
```python
from mys_crypto import envelope, primitives, ratchet


def _pair():
    sk = b"s" * 32
    bob_priv, bob_pub = primitives.generate_x25519_keypair()
    alice = ratchet.ratchet_init_alice(sk, bob_pub)
    bob = ratchet.ratchet_init_bob(sk, (bob_priv, bob_pub))
    return alice, bob, envelope.derive_transform_key(sk)


def test_serialize_round_trip_preserves_fields():
    alice, _, _ = _pair()
    blob = ratchet.serialize_state(alice)
    restored = ratchet.deserialize_state(blob)
    assert restored.dhs == alice.dhs
    assert restored.dhr == alice.dhr
    assert restored.rk == alice.rk
    assert restored.cks == alice.cks
    assert restored.ckr == alice.ckr
    assert (restored.ns, restored.nr, restored.pn) == (alice.ns, alice.nr, alice.pn)


def test_serialized_state_continues_conversation():
    alice, bob, tkey = _pair()
    # один обмен, затем сериализуем обе стороны и продолжаем из восстановленных
    blob = envelope.seal(alice, tkey, b"first")
    assert envelope.open_(bob, tkey, blob) == b"first"
    alice = ratchet.deserialize_state(ratchet.serialize_state(alice))
    bob = ratchet.deserialize_state(ratchet.serialize_state(bob))
    # ответ Боба -> DH-ratchet у Алисы
    blob = envelope.seal(bob, tkey, b"reply")
    assert envelope.open_(alice, tkey, blob) == b"reply"
    blob = envelope.seal(alice, tkey, b"third")
    assert envelope.open_(bob, tkey, blob) == b"third"


def test_serialized_state_preserves_skipped_keys():
    alice, bob, tkey = _pair()
    b1 = envelope.seal(alice, tkey, b"m1")
    b2 = envelope.seal(alice, tkey, b"m2")
    # доставляем m2 первым -> у Боба появляется пропущенный ключ для m1
    assert envelope.open_(bob, tkey, b2) == b"m2"
    bob = ratchet.deserialize_state(ratchet.serialize_state(bob))
    assert len(bob.mkskipped) == 1
    assert envelope.open_(bob, tkey, b1) == b"m1"
```

- [ ] **Step 2: Запустить, убедиться что падает**

Run: `.venv/bin/pytest tests/test_ratchet_persistence.py -v`
Expected: FAIL — `AttributeError: serialize_state`.

- [ ] **Step 3: Реализация**

Добавить в конец `src/mys_crypto/ratchet.py`:
```python
_STATE_VERSION = 1


def _put_opt(buf: bytearray, value: bytes | None) -> None:
    if value is None:
        buf.append(0)
    else:
        buf.append(1)
        buf += value


def _get_opt(mv: memoryview, pos: int) -> tuple[bytes | None, int]:
    flag = mv[pos]
    pos += 1
    if flag == 0:
        return None, pos
    value = bytes(mv[pos:pos + 32])
    return value, pos + 32


def serialize_state(state: RatchetState) -> bytes:
    buf = bytearray()
    buf.append(_STATE_VERSION)
    buf += state.dhs[0]
    buf += state.dhs[1]
    _put_opt(buf, state.dhr)
    buf += state.rk
    _put_opt(buf, state.cks)
    _put_opt(buf, state.ckr)
    buf += state.ns.to_bytes(4, "big")
    buf += state.nr.to_bytes(4, "big")
    buf += state.pn.to_bytes(4, "big")
    buf += len(state.mkskipped).to_bytes(4, "big")
    for (dh, n), mk in state.mkskipped.items():
        buf += dh
        buf += n.to_bytes(4, "big")
        buf += mk
    return bytes(buf)


def deserialize_state(blob: bytes) -> RatchetState:
    mv = memoryview(blob)
    if mv[0] != _STATE_VERSION:
        raise ValueError("unsupported ratchet state version")
    pos = 1
    dhs_priv = bytes(mv[pos:pos + 32]); pos += 32
    dhs_pub = bytes(mv[pos:pos + 32]); pos += 32
    dhr, pos = _get_opt(mv, pos)
    rk = bytes(mv[pos:pos + 32]); pos += 32
    cks, pos = _get_opt(mv, pos)
    ckr, pos = _get_opt(mv, pos)
    ns = int.from_bytes(mv[pos:pos + 4], "big"); pos += 4
    nr = int.from_bytes(mv[pos:pos + 4], "big"); pos += 4
    pn = int.from_bytes(mv[pos:pos + 4], "big"); pos += 4
    count = int.from_bytes(mv[pos:pos + 4], "big"); pos += 4
    mkskipped: dict[tuple[bytes, int], bytes] = {}
    for _ in range(count):
        dh = bytes(mv[pos:pos + 32]); pos += 32
        n = int.from_bytes(mv[pos:pos + 4], "big"); pos += 4
        mk = bytes(mv[pos:pos + 32]); pos += 32
        mkskipped[(dh, n)] = mk
    return RatchetState(
        dhs=(dhs_priv, dhs_pub), dhr=dhr, rk=rk, cks=cks, ckr=ckr,
        ns=ns, nr=nr, pn=pn, mkskipped=mkskipped,
    )
```

- [ ] **Step 4: Запустить, убедиться что проходит**

Run: `.venv/bin/pytest tests/test_ratchet_persistence.py -v`
Expected: PASS (3 теста).

- [ ] **Step 5: Commit**

```bash
git add src/mys_crypto/ratchet.py tests/test_ratchet_persistence.py
git commit -m "feat: add ratchet state serialization for persistence"
```

---

### Task 4: Глобальный кап mkskipped с вытеснением — крипто-ядро

**Files:**
- Modify: `src/mys_crypto/ratchet.py`
- Test: `tests/test_ratchet_persistence.py`

- [ ] **Step 1: Дописать падающий тест**

Добавить в `tests/test_ratchet_persistence.py`:
```python
def test_global_skip_cap_evicts_oldest(monkeypatch):
    monkeypatch.setattr(ratchet, "MAX_SKIP_SESSION", 5)
    alice, bob, tkey = _pair()
    blobs = [envelope.seal(alice, tkey, f"m{i}".encode()) for i in range(8)]
    # доставляем последнее -> Боб пропускает ключи m0..m6 (7 шт.), кап = 5
    assert envelope.open_(bob, tkey, blobs[7]) == b"m7"
    assert len(bob.mkskipped) == 5
    # старейшие (m0, m1) вытеснены -> не расшифровать
    import pytest
    with pytest.raises(Exception):
        envelope.open_(bob, tkey, blobs[0])
    # сохранившиеся (например m6) -> расшифровываются
    assert envelope.open_(bob, tkey, blobs[6]) == b"m6"
```

- [ ] **Step 2: Запустить, убедиться что падает**

Run: `.venv/bin/pytest tests/test_ratchet_persistence.py -k global_skip_cap -v`
Expected: FAIL — `AttributeError: MAX_SKIP_SESSION` или len != 5.

- [ ] **Step 3: Реализация**

В `src/mys_crypto/ratchet.py` рядом с `MAX_SKIP = 1000` добавить:
```python
MAX_SKIP_SESSION = 2000
```

Добавить помощник (после `_skip_message_keys`):
```python
def _store_skipped(state: RatchetState, key_id: tuple[bytes, int], mk: bytes) -> None:
    state.mkskipped[key_id] = mk
    while len(state.mkskipped) > MAX_SKIP_SESSION:
        oldest = next(iter(state.mkskipped))
        del state.mkskipped[oldest]
```

В `_skip_message_keys` заменить строку
```python
        state.mkskipped[(state.dhr, state.nr)] = mk
```
на
```python
        _store_skipped(state, (state.dhr, state.nr), mk)
```

- [ ] **Step 4: Запустить, убедиться что проходит**

Run: `.venv/bin/pytest tests/test_ratchet_persistence.py -v && .venv/bin/pytest -q`
Expected: PASS — новые тесты и весь прежний набор (регрессий нет).

- [ ] **Step 5: Commit**

```bash
git add src/mys_crypto/ratchet.py tests/test_ratchet_persistence.py
git commit -m "feat: add global mkskipped session cap with FIFO eviction"
```

---

### Task 5: Sidecar (открытые метаданные)

**Files:**
- Create: `src/mys_storage/sidecar.py`
- Test: `tests/test_sidecar.py`

- [ ] **Step 1: Написать падающий тест**

`tests/test_sidecar.py`:
```python
import base64

from mys_storage import sidecar


def test_new_sidecar_has_random_salt_and_defaults():
    a = sidecar.new_sidecar()
    b = sidecar.new_sidecar()
    assert a["format_version"] == 1
    assert a["kdf"]["algo"] == "argon2id"
    assert len(base64.b64decode(a["kdf"]["salt"])) == 16
    assert a["kdf"]["salt"] != b["kdf"]["salt"]          # соль случайна
    assert a["attempts"] == {"failed": 0, "lockout_until": None}
    assert a["duress"]["wipe_enabled"] is False


def test_write_read_round_trip(tmp_path):
    meta = sidecar.new_sidecar()
    path = tmp_path / "v.meta.json"
    sidecar.write_sidecar(str(path), meta)
    assert sidecar.read_sidecar(str(path)) == meta


def test_write_is_atomic_no_partial_file(tmp_path):
    path = tmp_path / "v.meta.json"
    sidecar.write_sidecar(str(path), sidecar.new_sidecar())
    # временный файл не остаётся рядом
    assert list(p.name for p in tmp_path.iterdir()) == ["v.meta.json"]
```

- [ ] **Step 2: Запустить, убедиться что падает**

Run: `.venv/bin/pytest tests/test_sidecar.py -v`
Expected: FAIL — `ModuleNotFoundError: mys_storage.sidecar`.

- [ ] **Step 3: Реализация**

`src/mys_storage/sidecar.py`:
```python
"""Открытый sidecar: несекретные KDF-параметры и счётчики попыток."""

import base64
import json
import os

SALT_LEN = 16

DEFAULT_KDF = {
    "algo": "argon2id",
    "time_cost": 3,
    "memory_cost": 262144,  # KiB = 256 MiB
    "parallelism": 4,
    "hash_len": 32,
}


def new_sidecar(params: dict | None = None) -> dict:
    kdf = dict(DEFAULT_KDF)
    if params:
        kdf.update(params)
    kdf["salt"] = base64.b64encode(os.urandom(SALT_LEN)).decode()
    return {
        "format_version": 1,
        "kdf": kdf,
        "attempts": {"failed": 0, "lockout_until": None},
        "duress": {"wipe_enabled": False, "threshold": 10},
    }


def write_sidecar(path: str, meta: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(meta, fh)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def read_sidecar(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)
```

- [ ] **Step 4: Запустить, убедиться что проходит**

Run: `.venv/bin/pytest tests/test_sidecar.py -v`
Expected: PASS (3 теста).

- [ ] **Step 5: Commit**

```bash
git add src/mys_storage/sidecar.py tests/test_sidecar.py
git commit -m "feat: add plaintext sidecar for KDF params and attempt counters"
```

---

### Task 6: Вывод ключа БД (kdf)

**Files:**
- Create: `src/mys_storage/kdf.py`
- Test: `tests/test_repositories.py` (временный мини-тест на kdf; перенесём фокус позже)

- [ ] **Step 1: Написать падающий тест**

`tests/test_repositories.py` (создать файл, начнём с kdf):
```python
from mys_crypto.secure import SecureBytes
from mys_storage import kdf


def test_derive_db_key_deterministic_and_secure():
    salt = b"saltsaltsaltsalt"
    k1 = kdf.derive_db_key(b"pw", salt, time_cost=1, memory_cost=8, parallelism=1, hash_len=32)
    k2 = kdf.derive_db_key(b"pw", salt, time_cost=1, memory_cost=8, parallelism=1, hash_len=32)
    assert isinstance(k1, SecureBytes)
    assert bytes(k1) == bytes(k2)
    assert len(k1) == 32


def test_derive_db_key_salt_sensitive():
    a = kdf.derive_db_key(b"pw", b"AAAAAAAAAAAAAAAA", time_cost=1, memory_cost=8, parallelism=1)
    b = kdf.derive_db_key(b"pw", b"BBBBBBBBBBBBBBBB", time_cost=1, memory_cost=8, parallelism=1)
    assert bytes(a) != bytes(b)
```

- [ ] **Step 2: Запустить, убедиться что падает**

Run: `.venv/bin/pytest tests/test_repositories.py -k derive_db_key -v`
Expected: FAIL — `ModuleNotFoundError: mys_storage.kdf`.

- [ ] **Step 3: Реализация**

`src/mys_storage/kdf.py`:
```python
"""Вывод ключа БД из мастер-пароля (Argon2id)."""

from mys_crypto import primitives
from mys_crypto.secure import SecureBytes


def derive_db_key(
    password: bytes,
    salt: bytes,
    *,
    time_cost: int = 3,
    memory_cost: int = 262144,
    parallelism: int = 4,
    hash_len: int = 32,
) -> SecureBytes:
    raw = primitives.argon2id(
        password, salt, hash_len,
        time_cost=time_cost, memory_cost=memory_cost, parallelism=parallelism,
    )
    return SecureBytes(raw)
```

- [ ] **Step 4: Запустить, убедиться что проходит**

Run: `.venv/bin/pytest tests/test_repositories.py -k derive_db_key -v`
Expected: PASS (2 теста).

- [ ] **Step 5: Commit**

```bash
git add src/mys_storage/kdf.py tests/test_repositories.py
git commit -m "feat: derive SQLCipher key from master password via Argon2id"
```

---

### Task 7: Схема и миграции

**Files:**
- Create: `src/mys_storage/schema.py`
- Create: `src/mys_storage/migrations.py`
- Test: `tests/test_migrations.py`

- [ ] **Step 1: Написать падающий тест**

`tests/test_migrations.py`:
```python
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
```

- [ ] **Step 2: Запустить, убедиться что падает**

Run: `.venv/bin/pytest tests/test_migrations.py -v`
Expected: FAIL — `ModuleNotFoundError: mys_storage.migrations`.

- [ ] **Step 3: Реализация**

`src/mys_storage/schema.py`:
```python
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
]

TARGET_VERSION = MIGRATIONS[-1][0]
```

`src/mys_storage/migrations.py`:
```python
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
```

- [ ] **Step 4: Запустить, убедиться что проходит**

Run: `.venv/bin/pytest tests/test_migrations.py -v`
Expected: PASS (3 теста).

- [ ] **Step 5: Commit**

```bash
git add src/mys_storage/schema.py src/mys_storage/migrations.py tests/test_migrations.py
git commit -m "feat: add DB schema and migration runner"
```

---

### Task 8: create_vault / open_vault + нечитаемость без ключа

**Files:**
- Create: `src/mys_storage/vault.py`
- Test: `tests/test_vault.py`

В этой задаче — базовый жизненный цикл без лимита попыток (он в Task 9). Параметры Argon2id в тестах занижены для скорости.

- [ ] **Step 1: Написать падающий тест**

`tests/test_vault.py`:
```python
import pytest

from mys_storage import open_vault, create_vault, WrongPassword, VaultExists

FAST = {"time_cost": 1, "memory_cost": 8, "parallelism": 1}


def _db(tmp_path):
    return str(tmp_path / "vault.db")


def test_create_then_open_round_trip(tmp_path):
    path = _db(tmp_path)
    v = create_vault(path, b"correct horse", params=FAST)
    v.settings.set("mode", b"decentralized")
    v.close()
    v2 = open_vault(path, b"correct horse")
    assert v2.settings.get("mode") == b"decentralized"
    v2.close()


def test_open_with_wrong_password_raises(tmp_path):
    path = _db(tmp_path)
    create_vault(path, b"right", params=FAST).close()
    with pytest.raises(WrongPassword):
        open_vault(path, b"wrong")


def test_create_existing_raises(tmp_path):
    path = _db(tmp_path)
    create_vault(path, b"pw", params=FAST).close()
    with pytest.raises(VaultExists):
        create_vault(path, b"pw", params=FAST)


def test_db_file_has_no_plaintext(tmp_path):
    path = _db(tmp_path)
    v = create_vault(path, b"pw", params=FAST)
    v.settings.set("marker", b"SUPER_SECRET_PLAINTEXT")
    v.close()
    raw = open(path, "rb").read()
    assert b"SUPER_SECRET_PLAINTEXT" not in raw
    assert b"SQLite format 3" not in raw  # зашифрованный заголовок
```

- [ ] **Step 2: Запустить, убедиться что падает**

Run: `.venv/bin/pytest tests/test_vault.py -v`
Expected: FAIL — `ImportError`/`AttributeError` (нет `create_vault`).

- [ ] **Step 3: Реализация**

`src/mys_storage/vault.py`:
```python
"""Жизненный цикл зашифрованного vault."""

import base64
import os

import sqlcipher3

from mys_crypto.secure import SecureBytes

from . import kdf, migrations, sidecar
from .errors import VaultExists, WrongPassword
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
    salt = base64.b64decode(meta["kdf"]["salt"])
    key = kdf.derive_db_key(password, salt, **_kdf_kwargs(meta))
    conn = sqlcipher3.connect(db_path)
    _apply_key(conn, key)
    if not _verify(conn):
        conn.close()
        key.wipe()
        raise WrongPassword()
    return Vault(conn, db_path, meta, key)
```

> Репозитории появятся в Task 12 — до тех пор `vault.py` импортирует их из ещё несуществующего модуля. Поэтому **Task 12 переносится перед прогоном этого теста**: реализуйте репозитории (Task 12) сразу после написания `vault.py`, либо временно создайте `repositories.py` с пустыми классами-заглушками и допишите в Task 12.

- [ ] **Step 4: Создать минимальные репозитории-заглушки**, чтобы импорт прошёл (полноценно — Task 12):

`src/mys_storage/repositories.py` (заглушки + SettingsRepo, который нужен тесту):
```python
"""Репозитории поверх соединения SQLCipher."""


class SettingsRepo:
    def __init__(self, conn):
        self._c = conn

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


class IdentitiesRepo:
    def __init__(self, conn):
        self._c = conn


class ContactsRepo:
    def __init__(self, conn):
        self._c = conn


class ConversationsRepo:
    def __init__(self, conn):
        self._c = conn


class MessagesRepo:
    def __init__(self, conn):
        self._c = conn


class RatchetRepo:
    def __init__(self, conn):
        self._c = conn
```

- [ ] **Step 5: Запустить, убедиться что проходит**

Run: `.venv/bin/pytest tests/test_vault.py -v`
Expected: PASS (4 теста).

- [ ] **Step 6: Commit**

```bash
git add src/mys_storage/vault.py src/mys_storage/repositories.py tests/test_vault.py
git commit -m "feat: add encrypted vault create/open lifecycle"
```

---

### Task 9: Ограничение попыток (прогрессивная задержка)

**Files:**
- Modify: `src/mys_storage/vault.py`
- Test: `tests/test_vault.py`

- [ ] **Step 1: Дописать падающий тест**

Добавить в `tests/test_vault.py`:
```python
import time as _time

from mys_storage import VaultLocked


def test_wrong_password_increments_and_locks(tmp_path):
    path = _db(tmp_path)
    create_vault(path, b"right", params=FAST).close()
    with pytest.raises(WrongPassword):
        open_vault(path, b"nope")
    # сразу повторный вход заблокирован задержкой
    with pytest.raises(VaultLocked):
        open_vault(path, b"right")


def test_successful_open_resets_attempts(tmp_path, monkeypatch):
    path = _db(tmp_path)
    create_vault(path, b"right", params=FAST).close()
    with pytest.raises(WrongPassword):
        open_vault(path, b"nope")
    # эмулируем истечение блокировки
    import mys_storage.vault as vault_mod
    monkeypatch.setattr(vault_mod, "_delay_for", lambda failed: 0.0)
    with pytest.raises(WrongPassword):
        open_vault(path, b"nope2")
    v = open_vault(path, b"right")
    assert v._meta["attempts"]["failed"] == 0
    v.close()
```

- [ ] **Step 2: Запустить, убедиться что падает**

Run: `.venv/bin/pytest tests/test_vault.py -k "locks or resets" -v`
Expected: FAIL — нет `VaultLocked`-логики.

- [ ] **Step 3: Реализация**

В `src/mys_storage/vault.py` добавить импорты:
```python
import time

from .errors import VaultExists, VaultLocked, WrongPassword
```

Добавить функцию задержки:
```python
_LOCK_CAP = 300.0  # секунд


def _delay_for(failed: int) -> float:
    return min(2.0 ** failed, _LOCK_CAP)


def _register_failure(meta: dict, meta_path: str) -> None:
    meta["attempts"]["failed"] += 1
    meta["attempts"]["lockout_until"] = time.time() + _delay_for(meta["attempts"]["failed"])
    sidecar.write_sidecar(meta_path, meta)
```

Переписать начало `open_vault` (проверка блокировки) и ветку ошибки:
```python
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
```

- [ ] **Step 4: Запустить, убедиться что проходит**

Run: `.venv/bin/pytest tests/test_vault.py -v`
Expected: PASS (все тесты vault).

- [ ] **Step 5: Commit**

```bash
git add src/mys_storage/vault.py tests/test_vault.py
git commit -m "feat: add progressive-delay attempt limiting on unlock"
```

---

### Task 10: Duress-wipe (опциональный флаг)

**Files:**
- Modify: `src/mys_storage/vault.py`
- Test: `tests/test_vault.py`

- [ ] **Step 1: Дописать падающий тест**

Добавить в `tests/test_vault.py`:
```python
def test_duress_wipe_destroys_vault(tmp_path, monkeypatch):
    path = _db(tmp_path)
    v = create_vault(path, b"right", params={**FAST})
    # включаем duress с порогом 2
    v._meta["duress"] = {"wipe_enabled": True, "threshold": 2}
    from mys_storage import sidecar as sc
    sc.write_sidecar(path + ".meta.json", v._meta)
    v.close()

    import mys_storage.vault as vault_mod
    monkeypatch.setattr(vault_mod, "_delay_for", lambda failed: 0.0)

    with pytest.raises(WrongPassword):
        open_vault(path, b"x")
    with pytest.raises(WrongPassword):
        open_vault(path, b"y")  # достигнут порог -> wipe

    import os
    assert not os.path.exists(path)
    assert not os.path.exists(path + ".meta.json")
```

- [ ] **Step 2: Запустить, убедиться что падает**

Run: `.venv/bin/pytest tests/test_vault.py -k duress -v`
Expected: FAIL — файлы не удаляются.

- [ ] **Step 3: Реализация**

В `src/mys_storage/vault.py` добавить функцию затирания и вызвать её в `_register_failure`:
```python
def _wipe_files(db_path: str, meta_path: str) -> None:
    for p in (db_path, meta_path):
        if os.path.exists(p):
            with open(p, "r+b") as fh:
                length = os.fstat(fh.fileno()).st_size
                fh.write(b"\x00" * length)
                fh.flush()
                os.fsync(fh.fileno())
            os.remove(p)
```

Изменить `_register_failure` (нужен `db_path`):
```python
def _register_failure(meta: dict, db_path: str, meta_path: str) -> None:
    meta["attempts"]["failed"] += 1
    duress = meta["duress"]
    if duress["wipe_enabled"] and meta["attempts"]["failed"] >= duress["threshold"]:
        _wipe_files(db_path, meta_path)
        return
    meta["attempts"]["lockout_until"] = time.time() + _delay_for(meta["attempts"]["failed"])
    sidecar.write_sidecar(meta_path, meta)
```

В `open_vault` обновить вызов:
```python
        _register_failure(meta, db_path, meta_path)
```

- [ ] **Step 4: Запустить, убедиться что проходит**

Run: `.venv/bin/pytest tests/test_vault.py -v`
Expected: PASS (все тесты vault, включая duress).

- [ ] **Step 5: Commit**

```bash
git add src/mys_storage/vault.py tests/test_vault.py
git commit -m "feat: add optional duress-wipe on attempt threshold"
```

---

### Task 11: Смена пароля (rekey)

**Files:**
- Modify: `src/mys_storage/vault.py`
- Test: `tests/test_vault.py`

- [ ] **Step 1: Дописать падающий тест**

Добавить в `tests/test_vault.py`:
```python
def test_change_password(tmp_path):
    path = _db(tmp_path)
    v = create_vault(path, b"old-pass", params=FAST)
    v.settings.set("k", b"v")
    v.change_password(b"old-pass", b"new-pass")
    v.close()
    with pytest.raises(WrongPassword):
        open_vault(path, b"old-pass")
    v2 = open_vault(path, b"new-pass")
    assert v2.settings.get("k") == b"v"
    v2.close()


def test_change_password_wrong_old_raises(tmp_path):
    path = _db(tmp_path)
    v = create_vault(path, b"old-pass", params=FAST)
    with pytest.raises(WrongPassword):
        v.change_password(b"WRONG", b"new-pass")
    v.close()
```

- [ ] **Step 2: Запустить, убедиться что падает**

Run: `.venv/bin/pytest tests/test_vault.py -k change_password -v`
Expected: FAIL — нет метода `change_password`.

- [ ] **Step 3: Реализация**

Добавить метод в класс `Vault`:
```python
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
```

- [ ] **Step 4: Запустить, убедиться что проходит**

Run: `.venv/bin/pytest tests/test_vault.py -v`
Expected: PASS (все тесты vault).

- [ ] **Step 5: Commit**

```bash
git add src/mys_storage/vault.py tests/test_vault.py
git commit -m "feat: add master password change via PRAGMA rekey"
```

---

### Task 12: Репозитории (полная реализация)

**Files:**
- Modify: `src/mys_storage/repositories.py`
- Test: `tests/test_repositories.py`

- [ ] **Step 1: Дописать падающий тест**

Добавить в `tests/test_repositories.py`:
```python
from mys_storage import create_vault

FAST = {"time_cost": 1, "memory_cost": 8, "parallelism": 1}


def _vault(tmp_path):
    return create_vault(str(tmp_path / "v.db"), b"pw", params=FAST)


def test_identities_crud(tmp_path):
    v = _vault(tmp_path)
    iid = v.identities.add(kind="x25519", public_key=b"P" * 32, private_key=b"S" * 32, label="me")
    row = v.identities.get(iid)
    assert row["kind"] == "x25519" and row["public_key"] == b"P" * 32
    v.close()


def test_contacts_and_conversations_and_messages(tmp_path):
    v = _vault(tmp_path)
    cid = v.contacts.add(public_key=b"K" * 32, fingerprint="ab:cd", alias="bob")
    conv = v.conversations.add(mode="decentralized", peer_contact_id=cid, title="bob")
    m1 = v.messages.add(conv, direction="out", body=b"hi", status="sent")
    v.messages.add(conv, direction="in", body=b"yo", status="received")
    msgs = v.messages.list(conv)
    assert [m["body"] for m in msgs] == [b"hi", b"yo"]
    v.messages.set_status(m1, "delivered")
    assert v.messages.list(conv)[0]["status"] == "delivered"
    v.close()
```

- [ ] **Step 2: Запустить, убедиться что падает**

Run: `.venv/bin/pytest tests/test_repositories.py -k "crud or conversations" -v`
Expected: FAIL — у репозиториев нет методов `add`/`get`/`list`.

- [ ] **Step 3: Реализация**

Заменить `src/mys_storage/repositories.py` (включить row_factory для dict-доступа):
```python
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


class MessagesRepo(_Base):
    def add(self, conversation_id, *, direction, body, status, wire_seq=None) -> int:
        now = time.time()
        cur = self._c.execute(
            "INSERT INTO messages(conversation_id, direction, body, status, wire_seq, sent_at, received_at)"
            " VALUES(?,?,?,?,?,?,?)",
            (conversation_id, direction, body, status, wire_seq,
             now if direction == "out" else None,
             now if direction == "in" else None),
        )
        self._c.commit()
        return cur.lastrowid

    def list(self, conversation_id):
        cur = self._c.execute(
            "SELECT * FROM messages WHERE conversation_id=? ORDER BY id", (conversation_id,)
        )
        cur.row_factory = _row_factory
        return cur.fetchall()

    def set_status(self, message_id: int, status: str) -> None:
        self._c.execute("UPDATE messages SET status=? WHERE id=?", (status, message_id))
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
```

- [ ] **Step 4: Запустить, убедиться что проходит**

Run: `.venv/bin/pytest tests/test_repositories.py -v`
Expected: PASS (kdf + identities + contacts/conversations/messages).

- [ ] **Step 5: Commit**

```bash
git add src/mys_storage/repositories.py tests/test_repositories.py
git commit -m "feat: implement storage repositories"
```

---

### Task 13: Атомарный приём входящего сообщения

**Files:**
- Modify: `src/mys_storage/vault.py`
- Test: `tests/test_vault.py`

Приём = вставка сообщения + сохранение нового состояния ratchet в **одной транзакции** (см. §8.1 спеки). Реализуем через `Vault.receive_message`, исключающий рассинхрон.

- [ ] **Step 1: Дописать падающий тест**

Добавить в `tests/test_vault.py`:
```python
from mys_crypto import ratchet, primitives


def test_receive_message_atomic(tmp_path):
    path = _db(tmp_path)
    v = create_vault(path, b"pw", params=FAST)
    conv = v.conversations.add(mode="decentralized")
    sk = b"s" * 32
    bob_priv, bob_pub = primitives.generate_x25519_keypair()
    bob = ratchet.ratchet_init_bob(sk, (bob_priv, bob_pub))
    v.ratchet.save_state(conv, bob)
    # имитируем доставку: обновлённое состояние + тело — одной операцией
    bob.ns = 7  # любое наблюдаемое изменение состояния
    mid = v.receive_message(conv, body=b"incoming", new_state=bob)
    assert v.messages.list(conv)[0]["body"] == b"incoming"
    assert v.ratchet.load_state(conv).ns == 7
    assert mid > 0
    v.close()


def test_receive_message_rolls_back_on_error(tmp_path):
    path = _db(tmp_path)
    v = create_vault(path, b"pw", params=FAST)
    conv = v.conversations.add(mode="decentralized")
    sk = b"s" * 32
    bob_priv, bob_pub = primitives.generate_x25519_keypair()
    bob = ratchet.ratchet_init_bob(sk, (bob_priv, bob_pub))
    v.ratchet.save_state(conv, bob)
    # передаём заведомо плохое состояние (None) -> транзакция должна откатиться
    with pytest.raises(Exception):
        v.receive_message(conv, body=b"bad", new_state=None)
    assert v.messages.list(conv) == []          # сообщение не сохранилось
    assert v.ratchet.load_state(conv).ns == 0    # состояние не изменилось
    v.close()
```

- [ ] **Step 2: Запустить, убедиться что падает**

Run: `.venv/bin/pytest tests/test_vault.py -k receive_message -v`
Expected: FAIL — нет метода `receive_message`.

- [ ] **Step 3: Реализация**

Добавить импорт в `vault.py`:
```python
from mys_crypto import ratchet as _ratchet
```

Добавить метод в класс `Vault`:
```python
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
```

> Примечание: репозитории делают собственный `commit()` для одиночных операций; `receive_message` использует прямой SQL внутри `with self._conn`, чтобы оба изменения попали в одну транзакцию.

- [ ] **Step 4: Запустить, убедиться что проходит**

Run: `.venv/bin/pytest tests/test_vault.py -v`
Expected: PASS (все тесты vault, включая атомарность).

- [ ] **Step 5: Commit**

```bash
git add src/mys_storage/vault.py tests/test_vault.py
git commit -m "feat: add atomic inbound message receive"
```

---

### Task 14: Публичный API и интеграционный тест

**Files:**
- Modify: `src/mys_storage/__init__.py`
- Test: `tests/test_storage_integration.py`

- [ ] **Step 1: Дополнить публичный API**

Заменить `src/mys_storage/__init__.py`:
```python
"""Локальное зашифрованное хранилище МЫС Desktop."""

from .errors import (
    CorruptVault,
    StorageError,
    VaultExists,
    VaultLocked,
    WrongPassword,
)
from .vault import Vault, create_vault, open_vault

__all__ = [
    "Vault",
    "create_vault",
    "open_vault",
    "StorageError",
    "VaultExists",
    "WrongPassword",
    "VaultLocked",
    "CorruptVault",
]
```

- [ ] **Step 2: Написать интеграционный тест**

`tests/test_storage_integration.py`:
```python
from mys_crypto import envelope, primitives, ratchet
from mys_storage import create_vault, open_vault

FAST = {"time_cost": 1, "memory_cost": 8, "parallelism": 1}


def test_full_conversation_persisted_across_reload(tmp_path):
    """Два устройства: состояние ratchet каждый шаг грузится из БД (имитация рестарта)."""
    a_path = str(tmp_path / "alice.db")
    b_path = str(tmp_path / "bob.db")
    av = create_vault(a_path, b"pw-a", params=FAST)
    bv = create_vault(b_path, b"pw-b", params=FAST)

    sk = b"z" * 32
    bob_priv, bob_pub = primitives.generate_x25519_keypair()
    tkey = envelope.derive_transform_key(sk)
    ca = av.conversations.add(mode="decentralized")
    cb = bv.conversations.add(mode="decentralized")
    av.ratchet.save_state(ca, ratchet.ratchet_init_alice(sk, bob_pub))
    bv.ratchet.save_state(cb, ratchet.ratchet_init_bob(sk, (bob_priv, bob_pub)))

    def send(vault, conv, text):
        state = vault.ratchet.load_state(conv)
        blob = envelope.seal(state, tkey, text)
        vault.ratchet.save_state(conv, state)
        return blob

    def recv(vault, conv, blob):
        state = vault.ratchet.load_state(conv)
        pt = envelope.open_(state, tkey, blob)
        vault.ratchet.save_state(conv, state)
        return pt

    # Alice -> Bob (несколько подряд)
    for i in range(3):
        assert recv(bv, cb, send(av, ca, f"a{i}".encode())) == f"a{i}".encode()
    # Bob -> Alice (DH-ratchet у Алисы)
    assert recv(av, ca, send(bv, cb, b"reply")) == b"reply"
    # Alice -> Bob снова, уже после реальной перезагрузки vault'ов с диска
    av.close(); bv.close()
    av = open_vault(a_path, b"pw-a")
    bv = open_vault(b_path, b"pw-b")
    assert recv(bv, cb, send(av, ca, b"after restart")) == b"after restart"
    av.close(); bv.close()


def test_out_of_order_delivery_persisted(tmp_path):
    a_path = str(tmp_path / "a.db")
    b_path = str(tmp_path / "b.db")
    av = create_vault(a_path, b"pw", params=FAST)
    bv = create_vault(b_path, b"pw", params=FAST)
    sk = b"z" * 32
    bob_priv, bob_pub = primitives.generate_x25519_keypair()
    tkey = envelope.derive_transform_key(sk)
    ca = av.conversations.add(mode="decentralized")
    cb = bv.conversations.add(mode="decentralized")
    av.ratchet.save_state(ca, ratchet.ratchet_init_alice(sk, bob_pub))
    bv.ratchet.save_state(cb, ratchet.ratchet_init_bob(sk, (bob_priv, bob_pub)))

    a = av.ratchet.load_state(ca)
    b1 = envelope.seal(a, tkey, b"m1")
    b2 = envelope.seal(a, tkey, b"m2")
    b3 = envelope.seal(a, tkey, b"m3")
    av.ratchet.save_state(ca, a)

    def recv(blob):
        st = bv.ratchet.load_state(cb)
        pt = envelope.open_(st, tkey, blob)
        bv.ratchet.save_state(cb, st)
        return pt

    assert recv(b3) == b"m3"
    assert recv(b1) == b"m1"
    assert recv(b2) == b"m2"
    av.close(); bv.close()
```

- [ ] **Step 3: Запустить весь набор тестов**

Run: `.venv/bin/pytest -v`
Expected: PASS — крипто-ядро (33) + новые тесты хранилища и крипто-дополнений.

- [ ] **Step 4: Commit**

```bash
git add src/mys_storage/__init__.py tests/test_storage_integration.py
git commit -m "test: add storage integration tests with persisted ratchet"
```

---

### Task 15: Обновить документацию проекта

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Отметить под-проект №2 как реализованный**

В разделе «Порядок реализации» пометить пункт 2 «Локальное хранилище» как ✅ с указанием `src/mys_storage/`. В разделе follow-up'ов крипто-ядра отметить закрытыми «Лимит на `mkskipped`» (глобальный кап) и «Зануление ключей» (`SecureBytes`, best-effort), уточнив остаточный долг (полный перевод цепочечных ключей ratchet на `SecureBytes`).

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: mark local storage done and update crypto follow-ups"
```

---

## Самопроверка плана

**Покрытие спецификации:**
- Зашифрованная БД + открытый sidecar (§3) — Tasks 5, 8 ✓
- Проверка пароля без верификатора (§3.2) — Task 8 (`_verify`) ✓
- Жизненный цикл мастер-пароля (§4) — Tasks 8, 11 ✓
- Прогрессивная задержка (§5) — Task 9 ✓
- Duress-wipe как флаг (§6) — Task 10 ✓
- `SecureBytes` / зануление (§7) — Tasks 2, 8, 11 ✓
- Схема БД (§8) — Task 7 ✓
- Атомарность приёма (§8.1) — Task 13 ✓
- Сериализация ratchet + глобальный кап `mkskipped` (§9) — Tasks 3, 4 ✓
- Публичный API (§10) — Tasks 1, 8, 14 ✓
- Миграции (§11) — Task 7 ✓
- Тесты (§13) — Tasks 2–14 (TDD: тест до реализации) ✓

**Согласованность имён:** `SecureBytes`, `serialize_state/deserialize_state`, `MAX_SKIP_SESSION`, `create_vault/open_vault`, `Vault.{settings,identities,contacts,conversations,messages,ratchet}`, `Vault.change_password/receive_message/close`, `derive_db_key`, `new_sidecar/read_sidecar/write_sidecar`, `migrate/TARGET_VERSION` — единообразны во всех задачах и тестах.

**Границы модулей:** хранилище хранит `bytes` от `serialize_state`, не разбирая их; `SecureBytes` и сериализация — в крипто-ядре; БД-код не проникает в `mys_crypto`. ✓

**Порядок задач:** крипто-дополнения (2–4) идут раньше, т.к. от них зависит хранилище. Репозитории-заглушки (Task 8) → полная реализация (Task 12), чтобы `vault.py` импортировался уже на Task 8. ✓

**Открытый долг (зафиксирован, не блокирует v1):** полный перевод цепочечных ключей ratchet на `SecureBytes`; калибровка параметров Argon2id под железо; поля централизованного синка (под-проект №6).
