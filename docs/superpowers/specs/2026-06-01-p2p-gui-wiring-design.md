# Спека: проброс P2P-режима в GUI

**Дата:** 2026-06-01
**Статус:** дизайн утверждён, к плану реализации
**Связано:** этап №7 e2e (`docs/superpowers/specs/2026-05-31-roadmap-continuation.md` §7,
follow-up №3 — боевой `/p2p` ещё не гонялся живым клиентом),
под-проект №4 (`docs/superpowers/specs/2026-05-30-decentralized.md`).

## Проблема

Децентрализованный (P2P) режим реализован в `src/mys_decentralized/` и доказан
e2e-тестами (`tests/test_e2e_p2p.py`, 2 зелёных), но **не подключён к GUI**.
В `src/mys_ui/app.py` боевой `main()` создаёт только `central_factory`;
`AppController.attach_service()` нигде не вызывается. Поэтому в запущенном
приложении вкладка P2P — локальная заглушка: ввод фразы создаёт локальную беседу
без сети (`controller.create_conversation` уходит в ветку `vault.conversations.add`,
т.к. `self._service is None`).

## Цель

С двух физических машин (в локалке и вне её) ввести общую секретную фразу и адрес
rendezvous → установить защищённый канал и обмениваться сообщениями вживую через
GUI. Порядок проверки: **сначала LAN** через встроенный `rendezvous_server`
(полностью под нашим контролем), **потом** боевой `wss://soufos.ru/p2p`.

## Контекст проводки (как есть)

- `main_window._on_mode` / «+ Новый диалог» в режиме `DECENTRALIZED` →
  `PhraseDialog` (сейчас только поле фразы) → `add_conversation(phrase,
  room_phrase=phrase)` → `controller.create_conversation` → при подключённом
  сервисе `self._service.start_session(phrase)` (возвращает id беседы).
- Для «Центра» есть `_CentralBridge(QObject)` — маршалит колбэки сервиса
  (`on_message(cid, lid)` / `on_state_change(str)` / `on_error(exc)`) из потока
  сервиса в Qt-поток через `signal.emit`. `P2PService` имеет **ту же** сигнатуру
  колбэков.
- `P2PService(vault, rendezvous_url, *, on_message, on_state_change, on_error,
  connect_timeout=10.0, ...)`. `RendezvousClient` ждёт полный WS-URL
  (`ws://…` / `wss://…`, напр. `wss://soufos.ru/p2p`).
- `RendezvousServer.start(host="127.0.0.1", port=0)` умеет биндиться на `0.0.0.0`,
  но отдельного runner'а нет.
- Транспорт: relay-first через rendezvous + UDP hole-punch **только на loopback**
  с откатом на relay. Две реальные машины (LAN или WAN) идут через **relay**
  rendezvous-сервера — это рабочий путь и не требует cross-NAT hole-punch.

## Решение (по компонентам)

### 1. `src/mys_ui/app.py` — фабрика P2P (зеркало `central_factory`)
- Добавить `_p2p_factory(vault, rendezvous_url, *, on_message, on_state_change,
  on_error)` → `P2PService(vault, rendezvous_url, on_message=…,
  on_state_change=…, on_error=…)`.
- Прокинуть в `AppController(central_factory=…, p2p_factory=_p2p_factory)`.
- Боевой запуск получает рабочий P2P; тесты подсовывают свою фабрику.

### 2. `src/mys_ui/controller.py` — ленивый жизненный цикл сервиса
- Хранить `self._p2p_factory`.
- `ensure_p2p_service(rendezvous_url, *, on_message, on_state_change, on_error)`:
  если сервиса нет или `rendezvous_url` сменился — остановить старый
  (`stop()`/cleanup), создать фабрикой, `start()`, `attach_service`. **Один**
  активный сервис за раз (хранить текущий `rendezvous_url`).
- `create_conversation(title, *, room_phrase=None, rendezvous_url=None)`: в режиме
  `DECENTRALIZED` с фразой, фабрикой и URL — сперва `ensure_p2p_service(...)`,
  затем существующая ветка `self._service.start_session(room_phrase)`.
- `lock()`: помимо `_central`, останавливать и `_service` (сейчас не глушится —
  утечка фонового потока/сокета), затем сбросить в `None`.

### 3. `src/mys_ui/dialogs/phrase.py` — поле «Rendezvous:»
- Второе поле `QLineEdit` с дефолтом `wss://soufos.ru/p2p` (вынести константой
  `DEFAULT_RENDEZVOUS`).
- Метод `rendezvous_url()` (рядом с `phrase()`), `strip()`.
- Для LAN пользователь вписывает `ws://<ip-машины-с-сервером>:<port>/p2p`.

### 4. `src/mys_ui/windows/main_window.py` — мост + неблокирующий старт
- `_P2PBridge(QObject)` с сигналами `message(int, int)` / `state(str)` /
  `error(str)` → слоты обновляют список бесед/чат (по образцу
  `_on_central_message` / `_on_central_state` / `_on_central_error`).
- На accept `PhraseDialog`: прочитать `phrase` + `rendezvous_url`, запустить
  **worker-поток** (как `_resume_worker` у «Центра»), т.к. `start_session`
  блокирующий (до `connect_timeout=10с` на коннект → фриз UI недопустим). В
  worker'е: `controller.ensure_p2p_service(url, on_message=…emit, …)` +
  `controller.create_conversation(phrase, room_phrase=phrase,
  rendezvous_url=url)`. Результат (id беседы / исключение) — сигналом в UI-поток;
  UI обновляет список или показывает предупреждение.
- Ошибки (неверная фраза/MITM/нет связи/таймаут) → предупреждающий диалог, без
  падения приложения.

### 5. `scripts/run_rendezvous.py` — LAN-харнесс
- Маленький runner: `RendezvousServer().start("0.0.0.0", port)` (порт — аргумент,
  дефолт напр. `8765`), печать подсказки с URL (`ws://<lan-ip>:<port>/p2p`),
  `run_forever` до Ctrl-C. Запускается на одной машине в LAN; обе машины вписывают
  её адрес в поле rendezvous. Путь `/p2p` сервером игнорируется (хендлер на любой
  путь) — оставляем для единообразия с боевым URL.
- Обновить `scripts/README.md` короткой инструкцией LAN-прогона.

### 6. Тесты
- **Юнит** (headless `QT_QPA_PLATFORM=offscreen`): `PhraseDialog` возвращает
  фразу и rendezvous-URL; дефолт URL присутствует.
- **Интеграция**: два `AppController` через встроенный `RendezvousServer` (как
  `test_e2e_p2p.py`, но путь контроллер→сервис): `ensure_p2p_service` →
  `create_conversation`/`start_session` → обмен сообщением → `on_message`
  доставлен. Фиксирует именно проводку фабрика→ensure→session.
- Существующие e2e P2P (2 шт.) остаются зелёными.

## Границы (не в этой итерации)

- Реальный cross-NAT UDP hole-punch (loopback-only; обе машины идут через relay).
- Групповые P2P, оффлайн-доставка, передача файлов (отложенный объём v1).
- Серверный `/p2p` за nginx правим по факту: если LAN зелёный, а soufos нет —
  разбираемся уже на серверной стороне (`vsc_web`), клиентская проводка к тому
  моменту доказана.
- Множественные одновременные P2P-беседы с разными rendezvous (один активный
  сервис за раз).

## Критерии готовности

1. В GUI режим P2P: ввод фразы + rendezvous-URL поднимает реальный
   `P2PService`, беседа появляется, отправка/приём идут через канал.
2. Две машины в LAN через `scripts/run_rendezvous.py` обмениваются сообщениями.
3. `lock()` корректно глушит P2P-сервис (нет висящих потоков/сокетов).
4. Юнит- и интеграционные тесты зелёные; e2e P2P не сломаны.
5. Переключение URL на `wss://soufos.ru/p2p` — следующий шаг проверки (вне строгих
   критериев этой итерации, т.к. зависит от боевого сервера).
