"""E2E-тесты режима «Центр» против РЕАЛЬНОГО локального ``vsc_web``.

В отличие от :mod:`tests.test_centralized_service` (фейковый in-process сервер),
здесь поднимается настоящий сервер ``../vsc_web`` в subprocess (его собственным
venv-интерпретатором, своя tmp-БД, свободный порт) и клиент ``CentralizedService``
гоняется против него по реальному HTTP + WebSocket.

Маркер ``e2e_server``: тесты **пропускаются**, если соседний репозиторий
``vsc_web`` или его venv недоступны (см. фикстуру ``live_vsc_web``).

Замечания по архитектуре теста:

* Методы ``CentralizedService`` блокирующие (исполняются в собственном потоке
  сервиса через ``run_coroutine_threadsafe().result()``). Реальный сервер живёт в
  **отдельном процессе**, а не на event loop теста, поэтому тесты — обычные
  синхронные функции (без ``asyncio.to_thread``-плясок из юнит-тестов сервиса).
* Сервер подписывает WS-соединение на комнаты пользователя **в момент авторизации**
  (``ws_centralized._rooms_for``). Поэтому для real-time доставки между двумя
  аккаунтами B должен стать ``RoomMember`` комнаты A **до** подключения B. Вступление
  в комнату из десктопа в v1 не реализовано (follow-up №6), поэтому членство
  инъектируется прямой записью в серверную SQLite — это документированный для v1
  обходной путь.
"""

from __future__ import annotations

import asyncio
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from mys_centralized.api_client import RestClient
from mys_centralized.service import CentralizedService
from mys_storage import create_vault

pytestmark = pytest.mark.e2e_server

# Быстрый Argon2id для vault (как в остальных тестах — не боевые параметры).
FAST = {"time_cost": 1, "memory_cost": 8, "parallelism": 1}

# vsc_web — соседний репозиторий рядом с vsc_desktop.
_VSC_WEB_DIR = Path(__file__).resolve().parents[2] / "vsc_web"
_VSC_WEB_PYTHON = _VSC_WEB_DIR / ".venv" / "bin" / "python"
_VSC_WEB_APP = _VSC_WEB_DIR / "app.py"


def _free_port() -> int:
    """Подобрать свободный TCP-порт (краткое окно гонки приемлемо для теста)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait(pred, timeout: float = 10.0, interval: float = 0.05) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return
        time.sleep(interval)
    raise AssertionError("условие не выполнено за таймаут")


class _LiveServer:
    def __init__(self, url: str, db_path: str):
        self.url = url
        self.db_path = db_path


@pytest.fixture(scope="module")
def live_vsc_web():
    """Поднять реальный vsc_web в subprocess (его venv, tmp-БД, свободный порт).

    Пропуск (``pytest.skip``), если репозиторий vsc_web или его venv недоступны —
    тогда e2e против реального сервера прогнать нечем (CI без соседнего checkout).
    """
    if not _VSC_WEB_PYTHON.exists() or not _VSC_WEB_APP.exists():
        pytest.skip(
            f"vsc_web недоступен (нет {_VSC_WEB_PYTHON} или {_VSC_WEB_APP}) — "
            "e2e против реального сервера пропущены"
        )

    workdir = tempfile.mkdtemp(prefix="mys_e2e_central_")
    db_path = os.path.join(workdir, "server.db")
    port = _free_port()
    url = f"http://127.0.0.1:{port}"

    env = dict(os.environ)
    env["DATABASE_URL"] = f"sqlite:///{db_path}"
    env["PORT"] = str(port)
    env["SECRET_KEY"] = "e2e-secret-not-for-production"
    env["SESSION_TYPE"] = "null"  # без файловых сессий — нам нужен только Bearer-API

    log_path = os.path.join(workdir, "server.log")
    log = open(log_path, "w")  # noqa: SIM115 — закрываем в teardown
    proc = subprocess.Popen(
        [str(_VSC_WEB_PYTHON), "app.py"],
        cwd=str(_VSC_WEB_DIR),
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )

    # Ждём готовности: GET / → 200. Если процесс упал — показываем лог и пропускаем.
    deadline = time.monotonic() + 30.0
    ready = False
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            log.flush()
            tail = Path(log_path).read_text(errors="replace")[-2000:]
            pytest.skip(f"vsc_web не стартовал (exit {proc.returncode}):\n{tail}")
        try:
            with urllib.request.urlopen(url + "/", timeout=1.0) as resp:
                if resp.status == 200:
                    ready = True
                    break
        except (urllib.error.URLError, ConnectionError, OSError):
            pass
        time.sleep(0.2)

    if not ready:
        proc.terminate()
        log.flush()
        tail = Path(log_path).read_text(errors="replace")[-2000:]
        pytest.skip(f"vsc_web не вышел в готовность за таймаут:\n{tail}")

    try:
        yield _LiveServer(url, db_path)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5.0)
        log.close()


def _inject_room_member(db_path: str, room_name: str, login: str) -> str:
    """Сделать ``login`` участником комнаты по имени напрямую в серверной SQLite.

    Возвращает строковый ``room_id`` комнаты. Обходной путь для v1: вступление в
    чужую комнату из десктопа не реализовано (см. модульный docstring).
    """
    conn = sqlite3.connect(db_path, timeout=10.0)
    try:
        row = conn.execute(
            "SELECT room_id FROM rooms WHERE name=? ORDER BY id DESC LIMIT 1",
            (room_name,),
        ).fetchone()
        assert row is not None, f"комната {room_name!r} не найдена на сервере"
        room_id = row[0]
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO room_members(room_id, login, joined_at, role) VALUES(?,?,?,?)",
            (room_id, login, now, "member"),
        )
        conn.commit()
        return room_id
    finally:
        conn.close()


def _make_service(tmp_path, name: str, *, on_message=None, on_state_change=None):
    vault = create_vault(str(tmp_path / f"{name}.db"), f"pw-{name}".encode(), params=FAST)
    svc = CentralizedService(
        vault,
        on_message=on_message,
        on_state_change=on_state_change,
    )
    svc.start()
    return svc, vault


# ---------------------------------------------------------------------------
# Тест 1: полный цикл одного клиента — регистрация, комната, отправка, история,
#         идемпотентность повторной отправки на реальном сервере.
# ---------------------------------------------------------------------------

def test_central_register_create_send_and_idempotency(live_vsc_web, tmp_path):
    svc, _vault = _make_service(tmp_path, "alice")
    user = f"alice_{uuid.uuid4().hex[:8]}"
    room_name = f"room_{uuid.uuid4().hex[:8]}"
    try:
        sess = svc.login(live_vsc_web.url, user, "pw-secret-1", register=True)
        assert sess.username == user and sess.token

        conv_id = svc.create_room(room_name)
        assert isinstance(conv_id, int)

        local_id = svc.send_message(conv_id, "привет e2e")
        assert isinstance(local_id, int)

        # Проверяем через реальный REST: сообщение долетело и история его содержит;
        # повторная отправка с тем же client_msg_id идемпотентна (один и тот же id,
        # без дубля в истории).
        async def _rest_checks():
            rc = RestClient(live_vsc_web.url, token=sess.token)
            try:
                rooms = await rc.list_rooms()
                room = next(r for r in rooms if r.name == room_name)
                msgs, _ = await rc.get_messages(room.id, limit=200)
                bodies_before = [m.body for m in msgs]

                m1 = await rc.post_message(room.id, "dup-e2e", "cid-fixed-e2e")
                m2 = await rc.post_message(room.id, "dup-e2e", "cid-fixed-e2e")

                msgs2, _ = await rc.get_messages(room.id, limit=200)
                dup_count = sum(1 for m in msgs2 if m.body == "dup-e2e")
                return bodies_before, m1.id, m2.id, dup_count
            finally:
                await rc.aclose()

        bodies, id1, id2, dup_count = asyncio.run(_rest_checks())
        assert "привет e2e" in bodies, f"отправленное сообщение не в истории: {bodies}"
        assert id1 == id2, "повторный POST с тем же client_msg_id должен вернуть тот же id"
        assert dup_count == 1, f"идемпотентность нарушена: дублей={dup_count}"
    finally:
        svc.stop()


# ---------------------------------------------------------------------------
# Тест 2: real-time доставка между двумя аккаунтами через живой /ws.
# ---------------------------------------------------------------------------

def test_central_realtime_delivery_two_accounts(live_vsc_web, tmp_path):
    user_a = f"alice_{uuid.uuid4().hex[:8]}"
    user_b = f"bob_{uuid.uuid4().hex[:8]}"
    room_name = f"rt_{uuid.uuid4().hex[:8]}"

    svc_a, _va = _make_service(tmp_path, "rt_a")
    b_messages: list[tuple[int, int]] = []
    b_states: list[str] = []
    svc_b, vb = _make_service(
        tmp_path, "rt_b",
        on_message=lambda cid, lid: b_messages.append((cid, lid)),
        on_state_change=b_states.append,
    )
    try:
        svc_a.login(live_vsc_web.url, user_a, "pw-a-secret", register=True)
        conv_a = svc_a.create_room(room_name)

        # B становится участником комнаты A ДО подключения B (иначе /ws не подпишет).
        _inject_room_member(live_vsc_web.db_path, room_name, user_b)

        # B входит: sync_all увидит комнату (B уже участник) → /ws подпишется на неё.
        svc_b.login(live_vsc_web.url, user_b, "pw-b-secret", register=True)
        # Дожидаемся "connected": после WS-ready клиент повторно синкается, а сервер
        # к этому моменту уже подписал соединение B на комнату.
        _wait(lambda: "connected" in b_states, timeout=15.0)
        time.sleep(0.3)  # запас на серверную подписку после отправки ready

        # A отправляет — у B нет иного источника этого сообщения, кроме WS-push
        # (первичный синк B уже отработал до отправки).
        svc_a.send_message(conv_a, "пинг от A")

        _wait(lambda: len(b_messages) >= 1, timeout=15.0)
        conv_b, local_b = b_messages[0]
        rows = vb.messages.list(conv_b)
        delivered = [r["body"] for r in rows if r["direction"] == "in"]
        assert "пинг от A".encode("utf-8") in delivered, (
            f"push не доставил сообщение: {delivered}"
        )
    finally:
        svc_b.stop()
        svc_a.stop()
