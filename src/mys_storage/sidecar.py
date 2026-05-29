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
