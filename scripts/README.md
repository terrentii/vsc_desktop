# scripts/

Вспомогательные скрипты разработки/CI.

## smoke.py — сквозной e2e-прогон обоих режимов

Поднимает и прогоняет сквозные сценарии для P2P и режима «Центр», возвращает код
выхода pytest (0 — всё зелёное) для использования как CI-гейт.

```bash
# из корня репозитория, лучше интерпретатором .venv
python scripts/smoke.py
```

### Что нужно

- **libsodium** (≥1.0.18) — для P2P-крипто (ristretto255 через ctypes). Скрипт
  ищет `libsodium.so*` в типовых местах (`/nix/store/*/lib`, `/usr/lib`,
  multiarch, `/usr/local/lib`) и кладёт каталог на `LD_LIBRARY_PATH`. Если
  автопоиск не находит — задайте путь явно:
  ```bash
  SODIUM_DIR=/path/to/libsodium/lib python scripts/smoke.py
  ```
- **Соседний `../vsc_web`** с собственным `.venv` — для e2e «Центра». Скрипт сам
  его НЕ поднимает: это делает фикстура `live_vsc_web` в
  `tests/test_e2e_centralized.py` (поднимает `vsc_web` в subprocess его
  интерпретатором `../vsc_web/.venv/bin/python`, на свободном порту, с временной
  SQLite, и сама гасит). Если `vsc_web` или его venv недоступны — тесты с маркером
  `e2e_server` **пропускаются** (P2P-половина всё равно прогоняется: она
  самодостаточна, поднимает встроенный `rendezvous_server`).

`QT_QPA_PLATFORM=offscreen` скрипт выставляет сам (headless-окружение тестов).

### Какие сценарии гоняются

- `tests/test_e2e_p2p.py` — два локальных клиента через встроенный
  `rendezvous_server`: многосообщенческий диалог, реконнект, порядок первого
  сообщения (PAKE-fail/MITM покрыты в `tests/test_decentralized_integration.py`).
- `tests/test_e2e_centralized.py` (маркер `e2e_server`) — клиент против **реального**
  `vsc_web`: регистрация → создание комнаты → отправка → история, идемпотентность
  повторной отправки, и **real-time доставка** между двумя аккаунтами через живой
  `/ws` (членство второго аккаунта инъектируется прямой записью `RoomMember` —
  вступление в чужую комнату из десктопа в v1 не реализовано).

### Встраивание в CI

Отдельный шаг пайплайна. Нужны два соседних checkout — `vsc_desktop` и `vsc_web`
(как соседние каталоги), у каждого свой `.venv`:

```bash
# подготовка (один раз на раннер)
( cd vsc_desktop && python -m venv .venv && .venv/bin/pip install -e ".[dev]" )
( cd vsc_web     && python -m venv .venv && .venv/bin/pip install -r requirements.txt pytest )
# (libsodium ставится системным пакетным менеджером или задаётся SODIUM_DIR)

# прогон
cd vsc_desktop && python scripts/smoke.py
```

Боевая проверка `/ws`/`/p2p` за nginx (eventlet+gunicorn, один воркер — реестры
in-memory per-process) — вне CI; см. решение Phase 0 в
`docs/superpowers/plans/2026-05-31-e2e-integration.md` и серверные спеки
`docs/superpowers/specs/2026-05-30-server-*.md`.
