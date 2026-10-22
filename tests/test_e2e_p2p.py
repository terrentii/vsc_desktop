"""E2E-тесты P2P через полный стек P2PService + встроенный RendezvousServer.

Сценарии «неверная фраза» (PAKEError), MITM и «пир недоступен» уже покрыты в
:mod:`tests.test_decentralized_integration`; данный модуль фокусируется на:

1. **Многосообщенческий двунаправленный диалог** — несколько сообщений в обе
   стороны, порядок и расшифровка гарантированы, vault персистирует историю.
2. **Реконнект на уровне сервиса** — один P2PService перезапускается на том же
   vault; ratchet-состояние переживает рестарт и последующий обмен расшифровывается
   корректно.
"""

import asyncio

import pytest

from mys_decentralized import P2PService, RendezvousServer
from mys_decentralized.protocol import Role
from mys_storage import create_vault, open_vault

FAST = {"time_cost": 1, "memory_cost": 8, "parallelism": 1}


async def _start_server() -> tuple[RendezvousServer, str]:
    server = RendezvousServer()
    host, port = await server.start("127.0.0.1", 0)
    return server, f"ws://{host}:{port}/p2p"


async def _wait_for(pred, timeout: float = 5.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if pred():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("условие не выполнено за таймаут")


# ---------------------------------------------------------------------------
# Тест 1: Многосообщенческий двунаправленный диалог
# ---------------------------------------------------------------------------

async def test_multimessage_bidirectional_dialog(tmp_path):
    """Два P2PService обмениваются несколькими сообщениями в обе стороны.

    INITIATOR шлёт 3 сообщения → ждём приёма, затем RESPONDER шлёт 3 →
    ждём приёма. Проверяем: порядок не нарушен, тексты расшифрованы верно,
    vault у обоих хранит историю с корректными направлениями.
    """
    server, url = await _start_server()
    av = create_vault(str(tmp_path / "a.db"), b"pw-a", params=FAST)
    bv = create_vault(str(tmp_path / "b.db"), b"pw-b", params=FAST)

    recv_a: list[bytes] = []
    recv_b: list[bytes] = []
    sa = P2PService(
        av, url, allow_direct=False, connect_timeout=3,
        on_message=lambda _cid, body: recv_a.append(body),
    )
    sb = P2PService(
        bv, url, allow_direct=False, connect_timeout=3,
        on_message=lambda _cid, body: recv_b.append(body),
    )
    sa.start()
    sb.start()
    try:
        phrase = "многосообщенческий тест диалог"
        conv_a, conv_b = await asyncio.gather(
            asyncio.to_thread(sa.start_session, phrase),
            asyncio.to_thread(sb.start_session, phrase),
        )

        # В Double Ratchet первым шлёт INITIATOR; RESPONDER — после первого входящего.
        if sa.role_of(conv_a) == Role.INITIATOR:
            init, init_conv, init_recv = sa, conv_a, recv_a
            resp, resp_conv, resp_recv = sb, conv_b, recv_b
            init_vault, init_cid = av, conv_a
            resp_vault, resp_cid = bv, conv_b
        else:
            init, init_conv, init_recv = sb, conv_b, recv_b
            resp, resp_conv, resp_recv = sa, conv_a, recv_a
            init_vault, init_cid = bv, conv_b
            resp_vault, resp_cid = av, conv_a

        # --- INITIATOR шлёт 3 сообщения ---
        init_msgs = ["сообщение-1", "сообщение-2", "сообщение-3"]
        for msg in init_msgs:
            await asyncio.to_thread(init.send, init_conv, msg)

        expected_resp = [m.encode() for m in init_msgs]
        await _wait_for(lambda: resp_recv == expected_resp)

        # Порядок сохранён
        assert resp_recv == expected_resp, f"порядок нарушен: {resp_recv}"

        # --- RESPONDER шлёт 3 ответа ---
        resp_msgs = ["ответ-1", "ответ-2", "ответ-3"]
        for msg in resp_msgs:
            await asyncio.to_thread(resp.send, resp_conv, msg)

        expected_init = [m.encode() for m in resp_msgs]
        await _wait_for(lambda: init_recv == expected_init)

        # Порядок сохранён
        assert init_recv == expected_init, f"порядок нарушен: {init_recv}"

        # --- Vault корректно сохранил историю ---
        init_messages = init_vault.messages.list(init_cid)
        resp_messages = resp_vault.messages.list(resp_cid)

        init_dirs = [m["direction"] for m in init_messages]
        resp_dirs = [m["direction"] for m in resp_messages]

        # У инициатора: 3 исходящих + 3 входящих
        assert init_dirs.count("out") == 3, f"у инициатора неправильно 'out': {init_dirs}"
        assert init_dirs.count("in") == 3, f"у инициатора неправильно 'in': {init_dirs}"

        # У ответчика: 3 входящих + 3 исходящих
        assert resp_dirs.count("in") == 3, f"у ответчика неправильно 'in': {resp_dirs}"
        assert resp_dirs.count("out") == 3, f"у ответчика неправильно 'out': {resp_dirs}"

        # Тела сохранены корректно
        init_out_bodies = [m["body"] for m in init_messages if m["direction"] == "out"]
        init_in_bodies = [m["body"] for m in init_messages if m["direction"] == "in"]
        assert init_out_bodies == [m.encode() for m in init_msgs]
        assert init_in_bodies == [m.encode() for m in resp_msgs]

    finally:
        await asyncio.to_thread(sa.stop)
        await asyncio.to_thread(sb.stop)
        await server.stop()


# ---------------------------------------------------------------------------
# Тест 2: Реконнект на уровне сервиса — ratchet переживает рестарт
# ---------------------------------------------------------------------------

async def test_service_level_reconnect_ratchet_continues(tmp_path):
    """Реконнект одного P2PService на том же vault не ломает ratchet.

    Сценарий:
    1. sa и sb устанавливают сессию и обмениваются сообщением.
    2. sb останавливается (P2PService.stop). Vault sb на диске сохранил
       ratchet-состояние.
    3. Создаём sb_new — новый P2PService на ТОМ ЖЕ файле vault (с тем же паролем).
    4. sa и sb_new повторно входят в rendezvous-сессию с той же фразой.
       Rendezvous снова выдаёт роли; open_session() видит существующее
       ratchet-состояние в vault sb_new и продолжает с него (не пересеивает).
    5. Стороны обмениваются сообщениями. Они расшифровываются — ratchet выжил.

    Примечание о семантике: open_session() использует seed_state только когда в
    vault нет сохранённого состояния для данного conversation_id. После первого
    обмена состояние есть → на реконнекте именно оно используется автоматически
    (см. session.py::open_session). Поэтому тест проверяет реальный механизм
    реконнекта, а не повторную инициализацию ratchet.

    Покрытие сессионного уровня (InMemoryTransport) есть в test_session.py::
    test_session_resumes_ratchet_after_reconnect; данный тест покрывает
    полный стек через P2PService + реальный rendezvous.
    """
    server, url = await _start_server()

    db_a = str(tmp_path / "a.db")
    db_b = str(tmp_path / "b.db")
    pw_a = b"pw-a"
    pw_b = b"pw-b"

    av = create_vault(db_a, pw_a, params=FAST)
    bv = create_vault(db_b, pw_b, params=FAST)

    recv_a: list[bytes] = []
    recv_b: list[bytes] = []

    sa = P2PService(
        av, url, allow_direct=False, connect_timeout=3,
        on_message=lambda _cid, body: recv_a.append(body),
    )
    sb = P2PService(
        bv, url, allow_direct=False, connect_timeout=3,
        on_message=lambda _cid, body: recv_b.append(body),
    )
    sa.start()
    sb.start()

    try:
        phrase = "реконнект сервис тест"
        conv_a, conv_b = await asyncio.gather(
            asyncio.to_thread(sa.start_session, phrase),
            asyncio.to_thread(sb.start_session, phrase),
        )

        # Определяем роли
        if sa.role_of(conv_a) == Role.INITIATOR:
            init, init_conv = sa, conv_a
            resp, resp_conv = sb, conv_b
            resp_vault, resp_cid = bv, conv_b
            init_vault, init_cid = av, conv_a
        else:
            init, init_conv = sb, conv_b
            resp, resp_conv = sa, conv_a
            resp_vault, resp_cid = av, conv_a
            init_vault, init_cid = bv, conv_b

        # Шаг 1: обмен до реконнекта
        msg_before = "до реконнекта"
        resp_recv = recv_b if resp is sb else recv_a
        await asyncio.to_thread(init.send, init_conv, msg_before)
        await _wait_for(lambda: len(resp_recv) == 1)
        assert resp_recv[-1] == msg_before.encode()

        # Шаг 2: останавливаем ОТВЕТЧИКА (resp)
        # Сохраняем данные vault для повторного открытия
        if resp is sb:
            resp_db, resp_pw = db_b, pw_b
        else:
            resp_db, resp_pw = db_a, pw_a

        await asyncio.to_thread(resp.stop)

        # Шаг 3: открываем vault ответчика и создаём новый P2PService
        resp_vault_new = open_vault(resp_db, resp_pw)
        recv_resp_new: list[bytes] = []
        resp_new = P2PService(
            resp_vault_new, url, allow_direct=False, connect_timeout=3,
            on_message=lambda _cid, body: recv_resp_new.append(body),
        )
        resp_new.start()

        # Шаг 4: оба пира снова входят в rendezvous с той же фразой.
        # Стороны согласовывают новый канал; open_session() у ответчика
        # видит сохранённое ratchet-состояние и продолжает с него.
        recv_init_new: list[bytes] = []

        # Перезапускаем инициатора тоже, чтобы обе стороны вошли заново
        # (rendezvous требует двух участников в комнате одновременно).
        # Используем тот же vault инициатора (состояние сохранено).
        if init is sa:
            await asyncio.to_thread(sa.stop)
            init_vault_new = open_vault(db_a, pw_a)
            init_new = P2PService(
                init_vault_new, url, allow_direct=False, connect_timeout=3,
                on_message=lambda _cid, body: recv_init_new.append(body),
            )
            init_new.start()
            conv_init_new, conv_resp_new = await asyncio.gather(
                asyncio.to_thread(init_new.start_session, phrase),
                asyncio.to_thread(resp_new.start_session, phrase),
            )
        else:
            await asyncio.to_thread(sb.stop)
            init_vault_new = open_vault(db_b, pw_b)
            init_new = P2PService(
                init_vault_new, url, allow_direct=False, connect_timeout=3,
                on_message=lambda _cid, body: recv_init_new.append(body),
            )
            init_new.start()
            conv_init_new, conv_resp_new = await asyncio.gather(
                asyncio.to_thread(init_new.start_session, phrase),
                asyncio.to_thread(resp_new.start_session, phrase),
            )

        # Шаг 5: обмен после реконнекта
        # Снова определяем роли в новой паре
        if init_new.role_of(conv_init_new) == Role.INITIATOR:
            first, first_conv = init_new, conv_init_new
            second, second_conv = resp_new, conv_resp_new
            first_recv, second_recv = recv_init_new, recv_resp_new
        else:
            first, first_conv = resp_new, conv_resp_new
            second, second_conv = init_new, conv_init_new
            first_recv, second_recv = recv_resp_new, recv_init_new

        await asyncio.to_thread(first.send, first_conv, "после реконнекта")
        await _wait_for(lambda: len(second_recv) >= 1)
        assert second_recv[-1] == "после реконнекта".encode(), \
            f"сообщение после реконнекта не расшифровано: {second_recv}"

        await asyncio.to_thread(second.send, second_conv, "ответ после реконнекта")
        await _wait_for(lambda: len(first_recv) >= 1)
        assert first_recv[-1] == "ответ после реконнекта".encode(), \
            f"ответ после реконнекта не расшифрован: {first_recv}"

    finally:
        # Останавливаем все сервисы, которые могут быть живы
        for svc in [sa, sb]:
            try:
                await asyncio.to_thread(svc.stop)
            except Exception:
                pass
        for svc_name in ["resp_new", "init_new"]:
            svc = locals().get(svc_name)
            if svc is not None:
                try:
                    await asyncio.to_thread(svc.stop)
                except Exception:
                    pass
        await server.stop()
