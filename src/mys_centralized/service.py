"""Оркестратор централизованного режима: asyncio в фоновом потоке + мост для UI.

Связывает REST-клиент, движок синхронизации и WebSocket-клиент в один сервис по
образцу ``mys_decentralized.service.P2PService``. Публичные методы (``login``/
``resume``/``send_message``/``logout``) вызываются из главного потока и планируют
корутины в собственный event loop через ``run_coroutine_threadsafe``. Колбэки
(``on_message``/``on_state_change``/``on_error``) вызываются из потока сервиса;
маршалинг в Qt-сигналы — задача вышестоящего UI-слоя (Qt здесь нет — граница
CLAUDE.md). Доступ к vault сериализуется его собственным ``_LockedConnection``.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable

from .account import (
    clear_session,
    load_session,
    load_wipe_on_logout,
    save_session,
    wipe_local_cache,
)
from .api_client import RestClient
from .errors import AuthError
from .models import Session
from .sync import SyncEngine
from .ws_client import WsClient

# on_message(conversation_id, local_message_id); on_state_change(state);
# on_error(exception). state ∈ {"synced","connected","disconnected","unauthorized"}.
OnMessage = Callable[[int, int], None]
OnStateChange = Callable[[str], None]
OnError = Callable[[Exception], None]


def _noop(*_args):
    pass


def _default_rest_factory(base_url: str, *, token: str | None = None) -> RestClient:
    return RestClient(base_url, token=token)


def _default_ws_factory(url: str, token: str) -> WsClient:
    return WsClient(url, token)


def _default_ws_url(server_url: str) -> str | None:
    """Вывести WS-эндпоинт из базового URL сервера (``…/ws``).

    ``https://host`` → ``wss://host/ws``; ``http://host`` → ``ws://host/ws``.
    Для нераспознанной схемы — ``None`` (live-канал не поднимается)."""
    for http, ws in (("https://", "wss://"), ("http://", "ws://")):
        if server_url.startswith(http):
            return ws + server_url[len(http):].rstrip("/") + "/ws"
    return None


class CentralizedService:
    def __init__(
        self,
        vault,
        *,
        ws_url: str | None = None,
        ws_url_factory: Callable[[str], str | None] | None = None,
        rest_factory: Callable[..., RestClient] | None = None,
        ws_factory: Callable[[str, str], WsClient] | None = None,
        on_message: OnMessage | None = None,
        on_state_change: OnStateChange | None = None,
        on_error: OnError | None = None,
        page_limit: int = 200,
    ):
        self._vault = vault
        # ``ws_url`` — явный override (тесты); иначе выводим из server_url входа.
        self._ws_url = ws_url
        self._ws_url_factory = ws_url_factory or _default_ws_url
        self._rest_factory = rest_factory or _default_rest_factory
        self._ws_factory = ws_factory or _default_ws_factory
        self._on_message = on_message or _noop
        self._on_state_change = on_state_change or _noop
        self._on_error = on_error or _noop
        self._page_limit = page_limit

        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()

        # Состояние активной сессии (живёт в loop-потоке).
        self._rest: RestClient | None = None
        self._sync: SyncEngine | None = None
        self._session: Session | None = None
        self._ws: WsClient | None = None
        self._ws_task: asyncio.Task | None = None

    # --- жизненный цикл потока/loop -------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run_loop, name="mys-central", daemon=True
        )
        self._thread.start()
        self._ready.wait()

    def _run_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        try:
            self._loop.run_forever()
        finally:
            self._loop.close()

    def _submit(self, coro, timeout: float | None = None):
        if self._loop is None:
            raise RuntimeError("сервис не запущен")
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return fut.result(timeout)

    def stop(self) -> None:
        if self._loop is None:
            return
        try:
            self._submit(self._shutdown(), timeout=10.0)
        except Exception:
            pass
        self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        self._thread = None
        self._loop = None
        self._ready.clear()

    async def _shutdown(self) -> None:
        await self._teardown_session()

    # --- потокобезопасный API -------------------------------------------------

    @property
    def session(self) -> Session | None:
        return self._session

    def login(
        self,
        server_url: str,
        username: str,
        password: str,
        *,
        register: bool = False,
        timeout: float = 30.0,
    ) -> Session:
        """Войти (или зарегистрироваться) → синк → live. Блокирует до конца синка.

        Провал авторизации (``AuthError``) или сети (``NetworkError``)
        пробрасывается вызывающему для показа в UI.
        """
        return self._submit(
            self._login(server_url, username, password, register), timeout=timeout
        )

    def resume(self, *, timeout: float = 30.0) -> Session | None:
        """Восстановить сохранённую сессию из vault → синк → live.

        Возвращает ``None``, если сохранённой сессии нет. Истёкший токен всплывёт
        как ``AuthError`` (через колбэк или из синка)."""
        return self._submit(self._resume(), timeout=timeout)

    def send_message(self, conversation_id: int, body: str, *, timeout: float = 15.0) -> int:
        """Отправить сообщение (REST, идемпотентно). Возвращает локальный id."""
        return self._submit(self._send(conversation_id, body), timeout=timeout)

    def logout(self, *, timeout: float = 10.0) -> None:
        """REST logout (best-effort) + очистка сессии в vault + остановка live."""
        self._submit(self._logout(), timeout=timeout)

    # --- корутины (исполняются в loop-потоке) ---------------------------------

    async def _login(self, server_url, username, password, register) -> Session:
        rest = self._rest_factory(server_url)
        try:
            if register:
                sess = await rest.register(username, password)
            else:
                sess = await rest.login(username, password)
        except Exception:
            await rest.aclose()
            raise
        await self._activate(rest, sess)
        return sess

    async def _resume(self) -> Session | None:
        sess = load_session(self._vault)
        if sess is None:
            return None
        rest = self._rest_factory(sess.server_url, token=sess.token)
        await self._activate(rest, sess)
        return sess

    async def _activate(self, rest: RestClient, sess: Session) -> None:
        """Сделать сессию активной: персист, первичный синк, запуск live-WS."""
        await self._teardown_session()  # на случай повторного входа
        self._rest = rest
        self._session = sess
        save_session(self._vault, sess)
        self._sync = SyncEngine(
            self._vault, rest, on_message=self._dispatch_message,
            page_limit=self._page_limit,
        )
        await self._sync.sync_all()
        self._on_state_change("synced")
        self._start_ws()

    def _dispatch_message(self, conv_id, local_id, _msg) -> None:
        self._on_message(conv_id, local_id)

    def _start_ws(self) -> None:
        if self._session is None:
            return
        url = self._ws_url or self._ws_url_factory(self._session.server_url)
        if url is None:
            return  # WS-эндпоинт не определён → работаем без live-канала
        self._ws = self._ws_factory(url, self._session.token)
        self._ws_task = self._loop.create_task(self._ws_loop(self._ws, self._sync))

    async def _ws_loop(self, ws: WsClient, sync: SyncEngine) -> None:
        try:
            async for event in ws.events():
                etype = event.get("type")
                if etype == "ready":
                    # После каждого (пере)подключения добираем историю от курсора —
                    # закрываем пропуски за время оффлайна (спека §7.5).
                    await sync.sync_all()
                    self._on_state_change("connected")
                elif etype == "message":
                    await sync.ingest_ws(event)
        except asyncio.CancelledError:
            raise
        except AuthError as exc:
            self._on_state_change("unauthorized")
            self._on_error(exc)
        except Exception as exc:  # сетевой/протокольный сбой live-канала
            self._on_state_change("disconnected")
            self._on_error(exc)

    async def _send(self, conversation_id, body) -> int:
        if self._sync is None:
            raise RuntimeError("нет активной сессии")
        return await self._sync.send(conversation_id, body)

    async def _logout(self) -> None:
        rest = self._rest
        if rest is not None:
            try:
                await rest.logout()  # пока клиент ещё открыт
            except Exception:
                pass  # best-effort — токен всё равно забываем
        await self._teardown_session()  # закроет REST-клиент
        clear_session(self._vault)
        if load_wipe_on_logout(self._vault):
            wipe_local_cache(self._vault)  # по настройке стираем локальную историю

    async def _teardown_session(self) -> None:
        """Остановить live-WS и закрыть REST, не трогая персист сессии в vault."""
        if self._ws is not None:
            self._ws.close()
        if self._ws_task is not None:
            self._ws_task.cancel()
            try:
                await self._ws_task
            except (asyncio.CancelledError, Exception):
                pass
            self._ws_task = None
        self._ws = None
        if self._rest is not None:
            try:
                await self._rest.aclose()
            except Exception:
                pass
        self._rest = None
        self._sync = None
        self._session = None
