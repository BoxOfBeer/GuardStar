# GuardStar — заметки по архитектуре (dev-MVP)

Цель документа: быстро отвечать на вопросы “где что живёт” и “через что проходит игровой тик”.

## Высокоуровневые слои

- **Web UI (Jinja + JS)**: `server/app/templates/*`, `server/app/static/*`
- **API (Flask)**: `server/app/routes/api.py`
- **Web-роуты (Flask)**: `server/app/routes/web.py` (логин/регистрация/страницы/админка)
- **Сервисы домена**:
  - `server/app/services/world_service.py` — главный “оркестратор” домена (пока монолит).
  - `server/app/services/outpost_service.py` — логика форпостов, модулей и их upkeep.
  - `server/app/services/supply_service.py` — снабжение/радиусы/хабы.
  - `server/app/services/discovery_service.py` — одноразовые находки руин/аномалий.
  - `server/app/services/balance_service.py` — загрузка JSON-пака баланса и вычисления (upkeep/travel).
  - `server/app/services/auto_tick.py` — планировщик автосола (APScheduler).
- **Данные (PostgreSQL)**: модели `server/app/db/models/*`, миграции `server/app/db/migrations/*`.
- **Баланс (JSON)**: `server/data/balance/*` (buildings/units/tech/races/economy/aliases/meta).

## Основной цикл “сол” (tick)

Источник истины: `WorldService.process_next_tick()` — выполняется либо:
- автосолом (`auto_tick.py`), либо
- вручную `POST /api/world/tick`.

Типичный порядок внутри тика (упрощённо):
- завершение исследований (PlayerTech).
- завершение ордеров флотов (FleetOrder) и связанные события/бой.
- upkeep форпостов и снабжения.
- энергия флотов / аварийный возврат.
- огонь форпостов по вражеским флотам.
- влияние/контроль клеток.
- производство на планетах + потребление еды/воды населением.
- логистика снабжения форпостов (еда/вода с хаба).
- имперский upkeep флотов (металл/кристалл) и локальный upkeep энергии флота.

## Где смотреть “экономику”

Сейчас расчёты распределены по `WorldService` и `OutpostService`.
Плановый рефактор: выделить `economy_service.py` (производство/расходы/агрегации) и оставить `WorldService` как оркестратор.

## Админка

- `GET /admin/world?token=...` — состояние тиков/автосола + настройки спавна.
- `GET /admin/accounts?token=...` — список аккаунтов и флаг playtest-аудита.

Токен: хранится **в БД** (`admin_config.admin_token_hash`), но первичная инициализация возможна через `ADMIN_TOKEN` в env при старте приложения.

