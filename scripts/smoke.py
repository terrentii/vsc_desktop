#!/usr/bin/env python3
"""Smoke-прогон сквозных e2e обоих режимов — для локали и CI.

Что делает:
  1. Готовит окружение: находит каталог libsodium и кладёт его на
     ``LD_LIBRARY_PATH`` (нужно P2P-крипто: ristretto255 через ctypes), плюс
     ``QT_QPA_PLATFORM=offscreen`` (UI-зависимости headless).
  2. Запускает оба e2e-файла одним прогоном pytest и возвращает его код выхода
     (для CI-гейта).

Серверы поднимаются самими тестами:
  * **«Центр»** — фикстура ``live_vsc_web`` в :mod:`tests.test_e2e_centralized`
    поднимает реальный соседний ``../vsc_web`` в subprocess (его venv, tmp-БД,
    свободный порт) и сама же его гасит; если vsc_web/venv недоступны — тест
    помечен маркером ``e2e_server`` и **пропускается**.
  * **P2P** — самодостаточен: встроенный ``rendezvous_server`` поднимается прямо
    в тесте, внешнего сервера не требует.

Поэтому отдельный запуск сервера здесь не нужен (и вреден — конфликт портов с
фикстурой). Smoke лишь готовит окружение и зовёт pytest.

Переменные окружения:
  * ``SODIUM_DIR`` — явный каталог с ``libsodium.so*`` (если автопоиск не находит).

Запуск:  ``python scripts/smoke.py``  (лучше интерпретатором ``.venv``).
"""

from __future__ import annotations

import glob
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Кандидаты на каталог libsodium (не рекурсивный обход всего /nix/store — быстро).
_SODIUM_GLOBS = (
    "/nix/store/*/lib/libsodium.so*",
    "/usr/lib/libsodium.so*",
    "/usr/lib/*/libsodium.so*",   # multiarch (напр. /usr/lib/x86_64-linux-gnu)
    "/usr/local/lib/libsodium.so*",
    "/lib/*/libsodium.so*",
)


def find_sodium_dir() -> str | None:
    explicit = os.environ.get("SODIUM_DIR")
    if explicit:
        return explicit
    for pattern in _SODIUM_GLOBS:
        hits = sorted(glob.glob(pattern))
        if hits:
            return str(Path(hits[0]).parent)
    return None


def venv_python() -> str:
    candidate = ROOT / ".venv" / "bin" / "python"
    return str(candidate) if candidate.exists() else sys.executable


def main() -> int:
    env = dict(os.environ)

    sodium = find_sodium_dir()
    if sodium:
        prev = env.get("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = sodium + (os.pathsep + prev if prev else "")
        print(f"[smoke] libsodium: {sodium}")
    else:
        print(
            "[smoke] ВНИМАНИЕ: libsodium не найден автопоиском — задайте SODIUM_DIR, "
            "иначе P2P-крипто-тесты упадут на импорте.",
            file=sys.stderr,
        )

    env["QT_QPA_PLATFORM"] = "offscreen"

    cmd = [
        venv_python(), "-m", "pytest",
        "tests/test_e2e_p2p.py", "tests/test_e2e_centralized.py",
        "-m", "e2e_server or not e2e_server", "-q",
    ]
    print(f"[smoke] запуск: {' '.join(cmd)}")
    # exec в подпроцесс через os.execve было бы проще, но нам нужен код возврата
    # и совместимость с Windows — используем обычный вызов.
    import subprocess

    return subprocess.call(cmd, cwd=str(ROOT), env=env)


if __name__ == "__main__":
    sys.exit(main())
