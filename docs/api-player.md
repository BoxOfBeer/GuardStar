# HTTP API игрока GuardStar

Справка для клиентов: веб-UI, боты, скрипты, внешние интеграции. Все пути ниже относительно префикса **`/api`** (blueprint регистрируется в `server/app/__init__.py` как `url_prefix="/api"`).

**Исходники маршрутов:** `server/app/routes/api/routes_core.py`, `routes_progress.py`, `routes_world_fleets.py`, `routes_buildings_fleets_combat.py`, `routes_planets.py`, `routes_chat.py`, `routes_alliance.py`.

**Версия и актуальность:** `GET /api/version` — поля `game_version` (см. `docs/GAME_VERSION`), `balance_schema_version`, `balance_pack_id` / `balance_pack_name`. После обновления сервера сравнивайте эти поля с ожиданиями клиента.

---

## Содержание

1. [Общие правила](#общие-правила)
2. [Полный реестр эндпоинтов](#полный-реестр-эндпоинтов)
3. [Быстрый старт (curl и Python)](#быстрый-старт-curl-и-python)
4. [Проверка связи и метаданные](#проверка-связи-и-метаданные-без-логина)
5. [Аутентификация и профиль](#аутентификация-и-профиль)
6. [Баланс, техи, экономика, эффекты](#баланс-техи-экономика-эффекты)
7. [Мир, карта, тик, снабжение](#мир-карта-тик-снабжение)
8. [Юниты и флоты](#юниты-и-флоты)
9. [Постройки и форпосты](#постройки-и-форпосты)
10. [Планеты и колонизация](#планеты-и-колонизация)
11. [Чат](#чат-игрок)
12. [Альянсы](#альянсы-фаза-1)
13. [Минимальный сценарий](#минимальный-сценарий-проверка--логин--карта--постройка)
14. [Расширенный учебник и таблицы ошибок](#расширенный-учебник-для-ботов-и-интеграций)
15. [HTML-страницы](#замечание-про-html-страницы)

---

## Общие правила

| Тема | Описание |
|------|----------|
| **Формат** | JSON: тела `POST` / `PATCH` — заголовок `Content-Type: application/json`. |
| **Сессия** | После `POST /api/register` или `POST /api/login` сервер выставляет **cookie-сессию Flask** (`session`). Клиент должен отправлять cookie на последующие запросы (`requests.Session()`, браузер, `curl -b/-c`). |
| **401** | `{"error": "not_authenticated"}` — нет сессии или сессия сброшена. |
| **403 (аккаунт)** | Для большинства эндпоинтов отключённый аккаунт приводит к очистке сессии и `{"error": "account_disabled"}` (исключения: `health`, `ready`, `version`, `register`, `login`, `logout` — см. `_SKIP_ACCOUNT_DISABLED` в `server/app/routes/api/__init__.py`). |
| **Координаты** | Слой `z` на сервере клампится в диапазон **−10 … 10** там, где он передаётся в мир. |
| **Окно карты** | Параметр `radius` для `/world/window`, `/buildings/list` клампится к **6 … 12** (шаги гекса от центра); константы `MAP_WINDOW_RADIUS_MIN/MAX` в `server/app/routes/api/common.py`. В ответе окна **`topology`: `"hex"`**; клетки — **диск** в осевых координатах `x`, `y` (аналог `q`, `r` в axial hex). |

**Типичные поля ответов:** `error` (строка), часто `ok: true|false`, иногда `detail`, доменные поля (`need`/`have`, `missing_techs`, …).

**Коды ответов (обзор):**

- **200** — успех для большинства GET и успешных POST с телом `ok: true` (редко ошибка логики всё же в JSON при 200 — смотрите `ok`).
- **400** — неверные параметры, игровой отказ (`ok: false` у части маршрутов).
- **401** — нет сессии или неверный код входа (`invalid_access_code` на `login`).
- **403** — `account_disabled`, `sector_not_visible` (разведка), `blocked_peer` (чат), `forbidden` (админ/чужие ресурсы), `not_in_alliance` (влияние альянса), и т.д.
- **404** — не найдено (например флот в `upkeep-preview`).
- **413** — слишком длинное сообщение чата (`message_too_long`).
- **429** — лимит чата (`rate_limited`).
- **500** / **503** — внутренняя ошибка, БД недоступна (`/ready`).

---

## Полный реестр эндпоинтов

Метод и путь от корня приложения (с префиксом `/api`). «Сессия» = валидная cookie после `login`/`register`, если не указано иначе.

| Метод | Путь | Сессия |
|--------|------|--------|
| GET | `/api/health` | нет |
| GET | `/api/ready` | нет |
| GET | `/api/version` | нет |
| POST | `/api/register` | создаёт сессию |
| POST | `/api/login` | создаёт сессию |
| POST | `/api/logout` | опционально |
| GET | `/api/me` | да |
| GET | `/api/balance` | да |
| GET | `/api/tech/state` | да |
| GET | `/api/effects/active` | да |
| GET | `/api/economy/summary` | да |
| POST | `/api/tech/start` | да |
| GET | `/api/supply/state` | да |
| POST | `/api/supply/hire_supplier` | да |
| GET | `/api/world/sector` | нет (player_id из cookie опционален) |
| POST | `/api/discovery/resolve` | да |
| GET | `/api/world/window` | да |
| POST | `/api/world/tick` | да |
| GET | `/api/units/status` | да |
| GET | `/api/world/state` | да |
| POST | `/api/world/recruit_population` | да |
| POST | `/api/world/autotick` | да |
| POST | `/api/world/admin/dev/purge_bandits` | да, админ |
| POST | `/api/world/admin/dev/fleet_spawn_lock` | да, админ |
| POST | `/api/units/move_scout` | да |
| POST | `/api/fleets/move` | да |
| POST | `/api/fleets/cancel_order` | да |
| GET | `/api/buildings/list` | да |
| POST | `/api/buildings/place` | да |
| POST | `/api/buildings/place_batch` | да |
| POST | `/api/buildings/placement_checks` | да |
| POST | `/api/buildings/dismantle` | да |
| POST | `/api/buildings/upgrade` | да |
| POST | `/api/outposts/build` | да |
| POST | `/api/outposts/build_checks` | да |
| POST | `/api/outposts/upgrade` | да |
| POST | `/api/outposts/modules/install` | да |
| POST | `/api/outposts/modules/upgrade` | да |
| POST | `/api/outposts/modules/dismantle` | да |
| POST | `/api/fleets/create` | да |
| POST | `/api/fleets/rename` | да |
| POST | `/api/fleets/adjust` | да |
| GET | `/api/fleets/<fleet_id>/upkeep-preview` | да |
| POST | `/api/fleets/save` | да |
| POST | `/api/fleets/disband` | да |
| POST | `/api/fleets/merge` | да |
| POST | `/api/fleets/split` | да |
| POST | `/api/fleets/combat_preview` | да |
| POST | `/api/fleets/combat_prompt_resolve` | да |
| POST | `/api/intel/scan_fleet` | да |
| POST | `/api/planets/colonize` | да |
| GET/POST | `/api/chat/global` | да |
| GET/POST | `/api/chat/private` | да |
| GET | `/api/chat/private/threads` | да |
| GET | `/api/chat/private/badge` | да |
| GET | `/api/chat/private/thread/meta` | да |
| POST | `/api/chat/private/thread/open` | да |
| PATCH | `/api/chat/private/thread/prefs` | да |
| POST | `/api/chat/private/thread/hide` | да |
| GET/POST | `/api/chat/blocks` | да |
| DELETE | `/api/chat/blocks/<blocked_id>` | да |
| POST | `/api/chat/global/<message_id>/hide` | да |
| DELETE | `/api/chat/global/<message_id>` | да |
| POST | `/api/chat/moderation/chat-ban` | да, персонал |
| POST | `/api/chat/moderation/account-ban` | да, персонал |
| GET/POST | `/api/chat/alliance` | да |
| POST | `/api/alliance/create` | да |
| POST | `/api/alliance/join` | да |
| POST | `/api/alliance/leave` | да |
| GET | `/api/alliance/me` | да |
| GET | `/api/alliance/influence_at` | да |

---

## Быстрый старт (curl и Python)

Подставьте базовый URL вашего стенда (`http://127.0.0.1:5000` и т.д.).

### curl: cookie-jar

```bash
BASE="http://127.0.0.1:5000"
curl -sS "$BASE/api/health"
curl -sS "$BASE/api/version"

curl -sS -c cookies.txt -X POST "$BASE/api/register" \
  -H "Content-Type: application/json" \
  -d "{\"display_name\":\"Бот-Тест\",\"race_id\":\"human\"}"

# В ответе будут player_id и access_code — сохраните access_code.
curl -sS -c cookies.txt -X POST "$BASE/api/login" \
  -H "Content-Type: application/json" \
  -d "{\"access_code\":\"ВАШ_32_СИМВОЛА_HEX_КОД\"}"

curl -sS -b cookies.txt "$BASE/api/me"
curl -sS -b cookies.txt "$BASE/api/world/state"
curl -sS -b cookies.txt "$BASE/api/world/window?radius=8&z=0"
```

Код доступа после регистрации — **32 шестнадцатеричных символа** (`secrets.token_hex(16)` в `AuthService`).

### Python: одна сессия на все запросы

```python
import requests

BASE = "http://127.0.0.1:5000"
s = requests.Session()

r = s.post(f"{BASE}/api/login", json={"access_code": "ваш_код"})
r.raise_for_status()

me = s.get(f"{BASE}/api/me").json()
balance = s.get(f"{BASE}/api/balance").json()
state = s.get(f"{BASE}/api/world/state").json()

place = s.post(
    f"{BASE}/api/buildings/placement_checks",
    json={
        "x": 0,
        "y": 0,
        "z": 0,
        "building_types": ["mine_t1", "reactor_t1"],
        "fleet_id": None,
    },
).json()
```

---

## Проверка связи и метаданные (без логина)

### `GET /api/health`

Живость процесса; **БД не проверяет**.

**Пример 200:**

```json
{
  "status": "ok",
  "app": "GuardStar",
  "build_id": "…"
}
```

`build_id` — идентификатор сборки/перезапуска (`BUILD_ID` в `server/app/build_info.py`), не путать с `game_version`.

### `GET /api/ready`

Проверка БД (`SELECT 1`).

- **200:** `{"status": "ready"}`
- **503:** `{"status": "not_ready", "error": "db_unavailable"}`

### `GET /api/version`

**Пример 200:**

```json
{
  "app": "guardstar",
  "game_version": "01.189",
  "balance_schema_version": 1,
  "balance_pack_id": "…",
  "balance_pack_name": "…",
  "features": {
    "z_layers": true,
    "procgen": true,
    "move_scout": true,
    "resource_tick": true,
    "manual_world_tick": true
  }
}
```

`features` — стабильный набор флагов возможностей клиента; расширяется по мере игры.

---

## Аутентификация и профиль

### `POST /api/register`

Создаёт игрока, резервирует отображаемое имя, генерирует код доступа, **сразу выставляет cookie-сессию**.

**Тело:**

```json
{
  "display_name": "Оператор-7",
  "race_id": "human"
}
```

- `display_name` — после нормализации пробелов; длина **3…64** символа; пустое → ошибка `display_name_required` (маппинг из кода `empty`).
- `race_id` — строка из баланса; по умолчанию сервер подставляет `"human"`, если поле пустое. Раса должна существовать в балансе и иметь `enabled !== false`, иначе **`400`** `{"error": "invalid_race_id"}`.

**Успех 200:**

```json
{
  "player_id": "550e8400-e29b-41d4-a716-446655440000",
  "access_code": "abcdef0123…"
}
```

**Типовые ошибки 400:** `display_name_required`, `too_short`, `too_long`, `taken`, `invalid_race_id`.

### `POST /api/login`

**Тело:** `{ "access_code": "…" }` — ровно тот код, что выдали при регистрации (32 hex-символа).

**Успех 200:** `{"ok": true, "player_id": "<uuid>"}`

**Ошибки:** `400` — `access_code_required`; `401` — `invalid_access_code`; `403` — `account_disabled`.

### `POST /api/logout`

Сброс сессии. **200:** `{"ok": true}`

### `GET /api/me`

Краткий обзор игрока и планет (склад столицы/колоний в терминах ресурсов и юнитов на планетах). **401** без сессии.

Структура строится в `WorldService.get_player_overview` (`server/app/services/world_service/_mixin_02.py`):

- Всегда: `player_id`, `display_name`, `planets` (массив), `is_game_admin`, `is_game_moderator`.
- Элемент `planets[]` для колонизированной планеты: `id`, `name`, `planet_class`, `is_capital`, `is_colonized: true`, `pos: {x,y}`, `resources` (metal, crystal, energy, fuel, food, water), `units: [{unit_type, qty}, …]`.
- Не колонизированная (внешняя) планета в списке владений: `is_colonized: false`, `status_ru`, `resources: null`, `units: []`.

Пример см. в разделе [Расширенный учебник](#расширенный-учебник-для-ботов-и-интеграций).

---

## Баланс, техи, экономика, эффекты

Нужна сессия.

### `GET /api/balance`

Полная выгрузка **публичного** баланса одним JSON.

**Корневые поля успешного ответа:**

| Поле | Смысл |
|------|--------|
| `ok` | `true` |
| `meta` | Версия пакета, схема и пр. из `meta.json` |
| `resources` | Описание типов ресурсов |
| `economy` | Глобальные числа (в т.ч. лимиты, бандиты, `intel_scan`, `alliance`, `citizen_recruit`, …) |
| `aliases` | В т.ч. **`building_aliases`** — источник истины для строк **`building_type`** в API построек |
| `races` | Список рас (объекты из баланса) |
| `units` | Все юниты |
| `buildings` | Все типы зданий |
| `outposts` | Типы форпостов (`id` = `outpost_type` в API) |
| `outpost_modules` | Типы модулей (`id` = `module_type`) |
| `tech` | Дерево технологий |

**Ошибки:** `401`; при не загруженном балансе на сервере — **`500`** с `ok: false`, `error: "balance_not_loaded"`, `detail`.

### `GET /api/tech/state`

Очередь исследований и запас **RP** (research points).

**Пример фрагмента:**

```json
{
  "ok": true,
  "current_tick": 10,
  "current_sol": 10,
  "research_points": 12.5,
  "research_points_per_sol": 2.5,
  "techs": [
    {
      "tech_id": "tech_mining_1",
      "status": "in_progress",
      "started_tick": 5,
      "started_sol": 5,
      "finish_tick": 15,
      "finish_sol": 15,
      "remaining_ticks": 5,
      "remaining_sols": 5
    }
  ]
}
```

Статусы строк `techs` в БД: в т.ч. `in_progress`, `done`. Поля `*_tick` и `*_sol` для игрока означают одно и то же число (номер **сола** мира).

### `GET /api/effects/active`

Активные модификаторы игрока на текущий тик: `{"ok": true, "current_tick": N, "effects": [ … ]}`. Состав `effects` зависит от `list_active_player_effects` — для точной схемы смотрите живой ответ и `server/app/services/player_research_effects.py`.

### `GET /api/economy/summary`

Query-параметр: **`include_external_buildings`** — `1` (по умолчанию) или `0`: влияет на учёт полевых построек в справочных агрегатах (`buildings.external_buildings` / `hidden`).

Развёрнутая сводка империи за **один сол** (и запасы). Основные ключи успешного ответа (`EconomyService.get_economy_summary`, не режим `for_hud_poll`):

- `ok`, `current_tick`, `current_sol`
- `research_points`, `research_points_per_sol`
- `treasury_home` — ресурсы на **первой** планете игрока по `created_at` (столица для операций «с дома»).
- `treasury_empire` — сумма по всем планетам владельца.
- `net_per_sol` — чистый приток/расход по империи за сол (производство минус население, логистика форпостов, апкип флотов, энергия флотов, форпосты).
- `net_home_per_sol` — аналогично только для домашней планеты (производство дома минус нужды населения дома).
- `production_per_sol` — суммарное «сырое» производство планет до вычета расходов.
- `costs_per_sol` — детализация: `population_vitals`, `outpost_supply_logistics`, `outpost_upkeep`, `fleet_empire_upkeep`, `fleet_energy_upkeep`.
- `expenses_aggregate_per_sol` — разница между производством и `net` по ресурсам.
- `construction_reference` — справочно: оценка «стоимости восстановления» построек и кораблей (не ежесолевой расход); внутри `note`, `buildings_replacement_cost`, `fleet_ships_replacement_cost`.
- `planets` — по каждой планете: `planet_id`, `name`, `pos`, `population`, `production_per_sol`, `population_upkeep_per_sol`.
- `buildings` — счётчики `planet_buildings`, `external_buildings`, `external_buildings_hidden`.
- `fleets` — краткий список флотов с `id`, `name`, `pos`, `ships`.
- `runway_sols` — по каждому ресурсу оценка «сколько солов хватит» при текущем тренде (`trend`, `approx_sols`).

### `POST /api/tech/start`

**Тело:** `{"tech_id": "some_tech"}`

При успехе **200** (фрагмент):

```json
{
  "ok": true,
  "tech_id": "tech_mining_1",
  "status": "in_progress",
  "started_tick": 11,
  "started_sol": 11,
  "finish_tick": 25,
  "finish_sol": 25,
  "research_time_multiplier": 1.0,
  "research_ticks_base": 20,
  "residual_time_ticks": 9,
  "research_ticks_adjusted": 9,
  "research_points_spent": 10.0,
  "research_points_after": 2.5,
  "blueprint_cache_consumed": false,
  "blueprint_discount": null,
  "field_data_required": [],
  "field_data_consumed": []
}
```

Дополнительные ошибки сверх перечисленных в учебнике: `tech_bad_prereq`, `tech_bad_field_data_requirements`, `player_not_found`, `balance_not_loaded` (**500**).

---

## Мир, карта, тик, снабжение

### `GET /api/world/sector?x=&y=&z=0`

Краткий «стаб» сектора. Сессия **не обязательна**: при наличии cookie подмешивается видимость для игрока.

### `GET /api/world/window`

**Query:**

| Параметр | Тип | По умолчанию | Описание |
|-----------|-----|----------------|----------|
| `radius` | int | 6 | Кламп 6…12 |
| `z` | int | 0 | Слой |
| `center_x`, `center_y` | int, опционально | null | Центр окна; если не заданы — сервер выбирает центр по миру/игроку (логика `WorldService.get_player_map_window`) |
| `reveal_fog` | 0/1 | 0 | Только для **`is_game_admin`**; иначе игнорируется |

Ответ большой; структура с `cells[]` → `row[]` → клетки с `objects[]` описана ниже в учебнике.

### `POST /api/discovery/resolve`

Разведка **видимой** клетки.

**Тело:** `{"x": 0, "y": 0, "z": 0}` (все целые).

**403** с `error: "sector_not_visible"` — клетка не в зоне видимости.

### `POST /api/world/tick`

Один игровой **тик** (сол) мира для всех игроков в инстансе. **200:** `{"ok": true, …}` плюс поля из `process_next_tick`.

### `GET /api/world/state`

Главный «толстый» снимок для UI: текущий **сол** мира (`current_sol` / `current_tick`), флоты, события, настройки автотика на уровне мира и т.д. Полезные поля для клиента:

- **`player_race_id`**, **`race_growth`**: `{ "no_passive_planet_food_water", "no_passive_population_growth" }` — флаги из `races.json` для текущей расы.
- **`home_planet.id`** — UUID домашней планеты.
- **`research`**: `{ "in_progress": bool, "tech_id": string|null, "progress_percent": int|null }` — для HUD науки: при активном исследовании у RP в топбаре может показываться **(N%)** готовности текущего теха; без очереди — только визуальный «простой» чипа.
- У **администратора** (`is_game_admin`) дополнительно может приходить **`admin_dev`**: `test_block_new_fleets`, `bandit_ai_every_n_ticks` (из баланса `economy.bandit_wilderness.ai_every_n_ticks` — как часто за тик выполняется блок ИИ корсаров).

Дополнительно сервер может добавлять:

- `balance_error`, `auto_tick_error` — строки диагностики при проблемах загрузки баланса/планировщика.
- `auto_tick_running`, `auto_tick_last_run_at`, `auto_tick_last_tick` — состояние фонового тика (после старта/включения автотика сервер выполняет **один сол сразу**, затем — каждые `auto_tick_interval_seconds`).
- `build_id` — дублирование с health для отладки.

### `POST /api/world/recruit_population`

Явный набор населения на **своей** колонии — только для рас с **`no_passive_population_growth`** в балансе.

**Тело:** `{ "planet_id": "<uuid>", "amount": <int> }` (допускается синоним **`count`** вместо `amount` на уровне парсера маршрута).

Лимит за запрос: `economy.citizen_recruit.max_population_per_request`. Стоимость: `metal_per_pop`, `crystal_per_pop`, `food_per_pop`, `water_per_pop`.

**Ошибки:** `recruit_not_available_for_race` (400); `planet_not_owned` (**403**); `invalid_uuid`, `invalid_amount`, `no_resources`, `population_cap`, `not_enough_resources` (с `need`/`have`).

### `POST /api/world/autotick`

**Тело:** `{"enabled": true, "interval_seconds": 5}`

- `enabled` — обязательный **bool**.
- `interval_seconds` — опционально; если передан, должен быть числом в **1…60**; иначе **`400`** `error: "interval_out_of_range"` с `min`/`max`.

Настройки пишутся в `WorldState` и дублируются в `app.config`; планировщик перезапускается. При сбое переключения возможен **`500`** `autotick_toggle_failed` с `detail`.

**Успех 200:**

```json
{
  "ok": true,
  "auto_tick_enabled": true,
  "auto_tick_interval_seconds": 5.0
}
```

### Админ: корсары и нагрузка

Только **`is_game_admin`** (иначе **403** `forbidden`):

- **`POST /api/world/admin/dev/purge_bandits`** — очистка мира от сущностей корсаров.
- **`POST /api/world/admin/dev/fleet_spawn_lock`** — тело строго с boolean `enabled`; ответ `{"ok": true, "test_block_new_fleets": …}`.

### `GET /api/supply/state?x=&y=&z=0`

Состояние снабжения для клетки. **400** `invalid_params`, если `x`/`y` не заданы как целые.

### `POST /api/supply/hire_supplier`

**Тело:** `{}` или `{"planet_id": "<uuid>"}` — логика найма на планете (см. `WorldService.hire_supplier`). При `ok: false` маршрут отвечает **400** с телом ошибки.

---

## Юниты и флоты

### Баланс юнитов (`GET /api/balance`): обзор с клетки, корпус, разблокировки

Поля задаются в записях юнитов в `units.json` (после загрузки баланса попадают в массив `units` ответа **`GET /api/balance`**).

- **`map_vision_radius_cells`** (необязательное поле; при загрузке баланса допускаются только целые **0…6**): вклад типа корабля в **пассивный обзор** (туман войны) с клетки, где стоит флот. Для **смешанного** состава флота сервер берёт **максимум** по присутствующим типам. Если поля нет, для логического типа **`scout`** сохраняется прежний эквивалент **2**, для остальных — **1** (обратная совместимость).

- **`fleet_energy_pool_bonus_per_ship`** и **`fleet_travel_fuel_flat_discount_per_ship`** (необязательные целые **0…500**): на каждый такой корабль в составе увеличивается **потолок энергии на борту** всего флота и уменьшается **суммарное топливо** на один перелёт (скидка не опускает расход ниже **1**, если базовый расход был больше нуля). Суммарный бонус энергии и скидка топлива по всему составу ограничены сервером сверху.

- **`fleet_composition_allowed`** (необязательное **bool**): при **`false`** тип не входит в состав игрока — сервер отбрасывает его из `composition` / `deltas` / `take` (с возвратом ресурсов на склад столицы по тем же правилам, что и при уменьшении числа кораблей). Радиус имперского снабжения по найму **снабженцев** на планете (`POST /api/supply/hire_supplier`) от этого не зависит.

- **Ось корпуса** в техах: `tech_hull_micro` … `tech_hull_heavy` (часть узлов может быть с `enabled: false` как резерв дерева). Разблокировка составных кораблей — через **`prereq_tech`** у юнита: должны быть выполнены **все** перечисленные техи (например средний корпус + сенсоры).

- **Utility-флоты (дорожная карта):** тот же шаблон «уровень корпуса + подсистема» планируется для ECM, relay, mobile refinery, repair tender, носителя сенсорных платформ и т.п. — отдельные `unit_id` и флаги поведения по мере появления механик.

- **Бой без лишних %%:** новые корабельные проекты в техах с **`effects: {}`**; глобальные `combat_*_multiplier` из старых тех по-прежнему могут влиять на расчёт боя — отдельные **профили оружия** (`weapon_profile` / `damage_type`) для ветвления урона зарезервированы на будущее; в текущем билде поля могут отсутствовать.

### `GET /api/units/status`

Статус юнитов/корабельных лимитов игрока — JSON целиком из `WorldService.get_units_status`.

### `POST /api/units/move_scout`

Legacy/обучающий приказ скауту. **Тело:** `{"x": 10, "y": -3, "z": 0}` (целые).

**Успех:** `{"ok": true, "status": "queued", …}`

### `POST /api/fleets/move`

**Тело:**

```json
{
  "fleet_id": "uuid",
  "x": 1,
  "y": 2,
  "z": 0,
  "force_attack": false
}
```

`force_attack` опционален, по умолчанию `false`. Целевая клетка не может быть клеткой планеты (`target_cell_has_planet`); флот встаёт на **соседних** клетках от планеты.

### `POST /api/fleets/cancel_order`

**Тело:** `{"fleet_id": "uuid"}`

### Флоты: создание, редактирование, бой

Все перечисленные маршруты — **POST**, `Content-Type: application/json`, нужна сессия.

#### `POST /api/fleets/create`

Создание флота на орбите/планете (логика сервера привязывает к `planet_id`).

```json
{
  "planet_id": "uuid-планеты-игрока",
  "name": "Разведка-1",
  "composition": {
    "scout": 2,
    "engineer": 1
  }
}
```

- `name` — опционально.
- Ключи `composition` — **логические** типы из баланса / `unit_aliases` (см. `GET /api/balance` → `aliases` и массив `units`).

#### `POST /api/fleets/rename`

```json
{ "fleet_id": "uuid", "name": "Новое имя" }
```

#### `POST /api/fleets/adjust`

Изменение состава **дельтами** относительно текущего (числа могут быть отрицательными — снимают корабли, с возвратом стоимости на столицу по правилам сервера).

```json
{
  "fleet_id": "uuid",
  "deltas": { "fighter": 1, "scout": -1 }
}
```

#### `POST /api/fleets/save`

Обновление имени и/или полного состава одним запросом. Должно быть хотя бы одно из полей `name` или `composition`.

```json
{
  "fleet_id": "uuid",
  "name": "Ударная",
  "composition": { "fighter": 3 }
}
```

Иначе **400** с `detail: "need_name_or_composition"`.

#### `POST /api/fleets/disband`

```json
{ "fleet_id": "uuid" }
```

#### `POST /api/fleets/merge`

Переливание кораблей с `source_fleet_id` в `target_fleet_id` (оба ваши, логика в `WorldService.merge_fleets`).

```json
{
  "target_fleet_id": "uuid",
  "source_fleet_id": "uuid"
}
```

#### `POST /api/fleets/split`

```json
{
  "fleet_id": "uuid",
  "take": { "scout": 1, "fighter": 0 }
}
```

`take` — сколько кораблей каждого логического типа забирает новый флот.

#### `POST /api/fleets/combat_preview`

Оценка исхода боя при прибытии на клетку **без** выполнения приказа.

```json
{
  "fleet_id": "uuid",
  "target_x": 5,
  "target_y": 12,
  "target_z": 0
}
```

Ответ при `ok: true` содержит расчётные поля (зависят от версии сервера — смотрите фактический JSON).

#### `POST /api/fleets/combat_prompt_resolve`

Ответ на промпт боя, если у флота висит приказ в состоянии ожидания решения игрока.

```json
{
  "order_id": "uuid-приказа",
  "attack": true
}
```

`attack` — строго **boolean** (`true`/`false` в JSON, не строка).

### `POST /api/intel/scan_fleet`

**Тело:** `{"scanner_fleet_id": "uuid", "target_fleet_id": "uuid"}`.

- Сканер — ваш флот **без** активного приказа (`queued` / `in_progress` / `pending_combat`).
- Цель — **чужой** флот; та же плоскость `z`; расстояние по гексу между центрами ≤ `intel_scan.max_range_hex` в [`server/data/balance/economy.json`](server/data/balance/economy.json) (по умолчанию **1**).
- Стоимость: **RP** игрока (`intel_scan.rp_cost`, по умолчанию **3**). Если у владельца цели в завершённых техах есть `intel_scan.defender_blocking_tech` (по умолчанию `tech_fleet_doctrine_1`), возвращается `ok: false`, `error: "intel_blocked"` — **RP не списываются**; в лог попадает событие `intel_blocked`.
- При успехе: `composition` (словарь логических типов → количество), `rp_spent`, `research_points_after`; события **`intel_scan_success`** (сканеру) и **`intel_scanned`** (владельцу цели).
- **Связь с разведкой:** пассивный радиус с флота (`map_vision_radius_cells`, см. выше) задаёт базовый слой «что видно в тумане» без RP; активный скан — отдельный шаг. В перспективе параметры сканов (дальность, сигнатуры, **detection strength**) можно увязать с классом разведчика и подсистемами сенсоров, не дублируя ветки глобальных процентов.

### `GET /api/fleets/<fleet_id>/upkeep-preview`

Path-параметр — UUID флота **строкой**. **404**, если флот не найден (`error: "not_found"`).

---

## Постройки и форпосты

### `GET /api/buildings/list`

Те же query-параметры, что у **`GET /api/world/window`**: `radius`, `z`, опционально `center_x`, `center_y`. Список зданий собирается из объектов карты с `type == "building"`.

**Пример фрагмента 200:** `{"ok": true, "buildings": [ { "x", "y", "z", "type", "id", … } ]}`

### `POST /api/buildings/place`

**Тело:**

```json
{
  "x": 5,
  "y": 12,
  "z": 0,
  "building_type": "mine_t1",
  "fleet_id": "optional-uuid-engineer-fleet"
}
```

`fleet_id` — если строительная логика требует инженерный флот на клетке (см. ответы `error` от сервера).

### `POST /api/buildings/place_batch`

Те же поля, что у `place` (`x`, `y`, `z`, `building_type`, опционально `fleet_id`), плюс **`count`** — целое **1…100**: сервер пытается поставить столько одинаковых зданий подряд в одной транзакции. При первой неудаче цикл останавливается.

**Успех 200:** `ok`, `placed` (сколько реально поставлено), `requested` (запрошенный `count` после клампа), `stopped_early` (bool, если остановились раньше из‑за ошибки/лимита слотов), `last_error` (последний ответ `place_building`, если остановились не на последней попытке), `building` (последнее успешно созданное здание).

**Ошибка 400:** если **`placed == 0`** — откат транзакции и тело как у неудачного `place` (например `not_enough_resources` с `need`/`have`).

### `POST /api/buildings/placement_checks`

Проверка нескольких типов сразу: `x`, `y`, `z`, `building_types` (массив строк), опционально `fleet_id`. Ответ: `results` по каждому типу.

При **`ok: true`** у кандидата дополнительно может быть блок **`build`**: **`time_ticks`** (сколько **солов** займёт стройка с учётом модификатора расы; в JSON имя поля историческое), **`ready_at_tick_preview`**, **`current_tick`** — для ETA в UI без списания ресурсов. В интерфейсе это удобно подписывать как «сол», не как серверный тик реального времени.

### `POST /api/outposts/build_checks`

Проверка постройки **без** записи в БД (удобно для UI и ботов перед списанием ресурсов).

**Тело:**

```json
{
  "x": 4,
  "y": 10,
  "z": 0,
  "fleet_id": "optional-uuid-engineer-fleet",
  "outpost_types": ["outpost_scout_t1", "outpost_mining_t1"]
}
```

- **`x`, `y`, `z`** — целые; для `z ≠ 0` общая проверка досягаемости вернёт **`z_not_supported_yet`** (как у полевых зданий).
- **`fleet_id`** — опционально: какой свой флот считать «строителем» на клетке (инженеры).
- **`outpost_types`** — массив строк; пустые строки отбрасываются.

**Успех 200:** `{"ok": true, "results": { "<тип>": { … } } }`  
Для каждого ключа типа значение либо **`{"ok": true}`**, либо **`{"ok": false, "error": "...", …}`** — тот же набор полей, что вернёт **`POST /api/outposts/build`** при отказе (включая **`need`** / **`have`** при **`not_enough_resources`**, **`need_distance`** / **`nearest`** при **`outpost_too_close`** и т.д.).

### `POST /api/outposts/build`

**Тело:** как у проверки, но одно поле типа:

```json
{
  "x": 4,
  "y": 10,
  "z": 0,
  "outpost_type": "outpost_scout_t1",
  "fleet_id": "optional-uuid-engineer-fleet"
}
```

**Успех 200:** `ok`, объект **`outpost`** (идентификатор, координаты, агрегированные поля из **`_outpost_stats`**: обзор, бой, слоты модулей и пр. — см. фактический JSON в ответе сервера).

**Игровые правила (MVP, важно для клиента):**

- Стоимость **`build.cost`** по ресурсам списывается со **склада домашней планеты** (первая планета игрока по `created_at`), как у полевых построек.
- На клетке должен стоять **свой флот с инженером**; при старте постройки с флота списывается **один** инженер (как у зданий в поле).
- Между **своими** активными/офлайн форпостами на том же **`z`** действует **минимальная дистанция Манхэттена**: не меньше **`vision.base_radius`** из определения типа форпоста в балансе (по умолчанию **6**). Иначе **`outpost_too_close`** и в ответе — **`need_distance`**, **`nearest`**, опционально **`nearest_outpost`**.
- Клетка не должна уже содержать активный форпост (**`cell_already_has_outpost`**) или здание (**`cell_already_built`**).
- Доступ к клетке проходит через ту же **`_can_build_at`**, что и полевая стройка: «район дома» (гекса-дистанция ≤ 3 до **любой** своей планеты) **или** инженерный флот на клетке; без второго вне зоны — **`engineer_required`**. Вражеская зона контроля — **`inside_enemy_control_zone`**.
- Требования по техам из баланса форпоста — **`tech_required`** с **`missing_techs`** / **`required_techs`**.

### `POST /api/outposts/upgrade`

**Тело:** `{"outpost_id": "<uuid-строка>"}`  

Повышает тип форпоста по ветке **`upgrade.to`** в балансе для текущего типа. Списывает **`upgrade.cost`** с домашнего склада; при нехватке — **`not_enough_resources`** (в теле есть **`need`**; поле **`have`** в коде апгрейда может отсутствовать — ориентируйтесь на **`need`** и свой снимок экономики).

**Типовые отказы:** `invalid_outpost_id`, `outpost_not_found`, `outpost_upgrade_unavailable` (нет ветки в балансе), `tech_required`, `no_resources` / `not_enough_resources`.

### Модули форпоста

Все маршруты под **`/api/outposts/modules/…`** требуют сессию; при **`ok: false`** — HTTP **400** с телом ошибки.

| Метод | Путь | Назначение |
|--------|------|------------|
| POST | `/outposts/modules/install` | Начать установку модуля: тело **`outpost_id`**, **`module_type`**. |
| POST | `/outposts/modules/upgrade` | Улучшение установленного модуля: тело **`module_id`** (UUID строки модуля в БД). |
| POST | `/outposts/modules/dismantle` | Снять активный модуль: тело **`module_id`**. |

**Установка (`install`):**

- На клетке форпоста нужен **свой флот с инженерами**; расход инженеров **`need_engineers` = slot_idx + 1`** (первый слот — 1 инженер, следующий — 2 и т.д.).
- Одновременно у игрока может быть **не больше одной** операции модуля в статусе **`in_progress`** по всей империи; иначе **`module_work_queue_full`**.
- Если заняты все **`module_slots_total`** форпоста — **`outpost_slots_full`**.
- После успеха модуль в **`in_progress`** до наступления **`finish_tick`** (длительность из **`build.time_ticks`** в балансе модуля); детали состояния форпоста смотрите в **`world/state`** или окне карты.

**Апгрейд модуля (`modules/upgrade`):** модуль должен быть **`active`**; иначе **`module_busy`**. Снова очередь **`module_work_queue_full`**, инженеры по формуле слота, в **`in_progress`** выставляется **`pending_module_type`** до завершения тика.

**Демонтаж (`dismantle`):** только **`active`** модуль; инженеры **возвращаются** на флот на клетке (обратно пропорционально слоту). В **`in_progress`** снять нельзя (**`module_busy`**).

Идентификаторы **`module_id`** приходят из состояния мира / детализации форпоста в API (не путать с **`module_type`** из баланса).

### `POST /api/buildings/dismantle` / `POST /api/buildings/upgrade`

**Тело:** `{"building_id": "uuid"}`

---

## Планеты и колонизация

### `POST /api/planets/colonize`

**Тело:**

```json
{
  "planet_id": "uuid",
  "fleet_id": "uuid"
}
```

Оба поля обязательны и должны быть **строками** UUID (иначе **`invalid_payload`**).

**Успех:** `{"ok": true, "planet_id": "<uuid>"}`

**Игровые условия (MVP, `colonize_planet` в `_mixin_08_planets_world.py`):**

- Планета существует, владелец — нейтральный мир, не колонизирована.
- Флот игрока на **`z = 0`**, на клетке планеты **или** в соседней по гексу клетке (`hex_distance` ≤ 1).
- Во флоте есть хотя бы один корабль с флагом **`colonize_planet`** в `units.json` (`flags`).
- Выполнены требования по **тиру тех** и списку **`colonize_required_tech_ids`** из `planet_types.json` для класса планеты.
- На столице есть минимум **300 metal** и **200 crystal** (жёстко в коде MVP).
- При успехе расходуется **один** «колонизатор» из состава.

**Типовые `error` при `ok: false` (для колонизации маршрут отвечает HTTP 400):**

| `error` | Смысл |
|---------|--------|
| `invalid_payload` | Неверные типы полей в JSON |
| `invalid_uuid` | Невалидный UUID планеты или флота |
| `balance_unavailable` | Нет баланса на сервере |
| `planet_not_found` | Нет такой планеты |
| `not_neutral_planet` | У планеты уже есть владелец-игрок |
| `already_colonized` | Флаг колонизации уже установлен |
| `fleet_not_found` | Нет флота или чужой флот |
| `z_not_supported_yet` | Флот не на слое z=0 |
| `fleet_not_adjacent_to_planet` | Дальше 1 гекса от планеты |
| `no_colonizer_in_fleet` | Нет подходящего юнита |
| `tech_tier_too_low` | Нужен больший макс. завершённый тир; см. `need_tier` |
| `tech_required` | Не хватает тех из `planet_types`; см. `required_techs` |
| `no_capital_planet` | Нет столицы в БД |
| `no_resources` | Нет строки ресурсов на столице |
| `not_enough_resources` | Мало металла/кристалла; см. `need` |

---

## Чат (игрок)

Все маршруты требуют сессию. Глобальный чат:

- **GET** `/api/chat/global?since_id=<int>` — опциональная подгрузка с id.
- **POST** `/api/chat/global` — `{"body": "текст"}`.

Приватный чат:

- **GET** `/api/chat/private?peer_id=<uuid>&since_id=<int>` — `peer_id` обязателен.
- **POST** `/api/chat/private` — `{"peer_id": "…", "body": "…"}`.

Нити и настройки:

- **GET** `/api/chat/private/threads`
- **GET** `/api/chat/private/badge`
- **GET** `/api/chat/private/thread/meta?peer_id=<uuid>`
- **POST** `/api/chat/private/thread/open` — `{"peer_id": "…", "send_read_receipts": false}`
- **PATCH** `/api/chat/private/thread/prefs` — `{"peer_id": "…", "send_read_receipts": true}`
- **POST** `/api/chat/private/thread/hide` — `{"peer_id": "…"}`

Блокировки:

- **GET** `/api/chat/blocks`
- **POST** `/api/chat/blocks` — `{"blocked_id": "<uuid>"}`
- **DELETE** `/api/chat/blocks/<blocked_id>`

Скрытие/удаление своих сообщений в глобале:

- **POST** `/api/chat/global/<message_id>/hide`
- **DELETE** `/api/chat/global/<message_id>`

Альянсовый канал (только члены альянса):

- **GET** `/api/chat/alliance?alliance_id=<uuid>&since_id=<int>`
- **POST** `/api/chat/alliance` — `{"alliance_id": "<uuid>", "body": "…"}`

Коды: **429** `rate_limited`, **413** `message_too_long`, **403** `blocked_peer` / `forbidden` (альянс).

### Модерация (персонал)

`POST /api/chat/moderation/chat-ban` — тело `{"player_id": "<uuid>", "hours": 24}`.

`POST /api/chat/moderation/account-ban` — тело `{"player_id": "<uuid>", "disable": true}`.

Для обычного игрока/бота без прав ответ будет **`403`** (`forbidden` / `admin_only`).

---

## Альянсы (фаза 1)

Экономика и снабжение остаются **персональными**. Альянс даёт тег, код приглашения, чат, отображение «союзник» на карте, превью **совместного влияния** в клетке (сумма `control_value` членов с капом `economy.alliance.influence_cell_cap`).

### `POST /api/alliance/create`

```json
{
  "display_name": "Империя Рассвета",
  "tag": "DAWN01"
}
```

Допускается ключ `name` вместо `display_name`. Тег: после нормализации **2…8** символов **`A–Z`/`0–9`**. Ошибки: `already_in_alliance`, `invalid_display_name`, `invalid_tag`, `tag_taken`, `join_code_collision` (крайне редко).

**Успех:** `join_code` внутри объекта `alliance` (12 символов **верхний регистр + цифры**).

### `POST /api/alliance/join`

```json
{ "join_code": "ABCD1234EFGH" }
```

Допускается ключ `code`. Код сравнивается в верхнем регистре; слишком короткая строка (**< 10 символов** после trim) даёт **`invalid_join_code`** без поиска в БД.

Ошибки: `already_in_alliance`, `alliance_not_found`, `alliance_full`, `invalid_join_code`, `invalid_player_id`.

### `POST /api/alliance/leave`

Без тела. Если выходящий — **лидер**, альянс удаляется: в ответе `disbanded: true`.

### `GET /api/alliance/me`

Вне альянса: `{"ok": true, "alliance": null}`. В альянсе: `id`, `display_name`, `tag`, **`join_code` только у лидера** (у членов `null`), `my_role`, `members[]` с `player_id`, `display_name`, `role`.

### `GET /api/alliance/influence_at?x=&y=&z=0`

Для члена альянса: `sum`, `capped`, `cap`, `alliance_id`. **403** `not_in_alliance`, если игрок не в организации.

---

## Минимальный сценарий «проверка → логин → карта → постройка»

1. `GET /api/health` и при необходимости `GET /api/ready`.
2. `GET /api/version` — зафиксировать `game_version` / `balance_schema_version`.
3. `POST /api/login` с JSON и сохранением cookie.
4. `GET /api/balance` — валидные типы: `buildings`, `aliases.building_aliases`, `outposts`, `outpost_modules`, `units`.
5. `GET /api/world/window?radius=6&z=0` — картинка сектора вокруг центра по умолчанию.
6. `POST /api/buildings/placement_checks` или `POST /api/outposts/build_checks` — проверка без списания ресурсов.
7. `POST /api/buildings/place` / `place_batch` или `POST /api/outposts/build`.
8. `POST /api/world/tick` или ожидание автотика.

---

## Расширенный учебник (для ботов и интеграций)

Краткого списка эндпоинтов недостаточно, если клиент должен восстанавливать логику после ошибок. Ниже — практика: cookie, порядок опроса, частые `error`, минимальный цикл.

### Сессия / cookie

- После **`POST /api/login`** или **`POST /api/register`** сервер ставит cookie сессии Flask.
- Любой последующий **`GET/POST /api/...`** должен **отправлять те же cookie**.
- **Python:** один экземпляр `requests.Session()` — логин один раз, затем все вызовы через этот объект.
- **`curl`:**  
  `curl -c jar.txt -X POST …/api/login -H "Content-Type: application/json" -d "{\"access_code\":\"…\"}"`  
  затем  
  `curl -b jar.txt …/api/me`

Пример связки **`health` → `login` → `me`**:

```bash
curl -sS "https://example.com/api/health"
curl -sS -c cookies.txt -X POST "https://example.com/api/login" \
  -H "Content-Type: application/json" \
  -d '{"access_code":"YOUR_CODE"}'
curl -sS -b cookies.txt "https://example.com/api/me"
```

### Что запрашивать в каком порядке

| Шаг | Зачем |
|-----|--------|
| `GET /api/version` | Версия клиента не расходится с сервером. |
| `GET /api/me` или `GET /api/world/state` | Позиция дома, ресурсы, флоты, номер текущего **сола** (`current_tick` / `current_sol`). |
| `GET /api/balance` | Справочник типов и стоимостей. |
| `GET /api/world/window` | Сетка клеток под стройку/разведку. |
| `POST /api/buildings/placement_checks` | Проверка типов зданий без списания ресурсов. |
| `POST /api/outposts/build_checks` | То же для форпостов перед **`/outposts/build`**. |

### Откуда брать `building_type` для `POST /api/buildings/place`

Сервер нормализует строку к **нижнему регистру** и проверяет ключ в **`aliases.building_aliases`**. Источник истины для API — **алиасы** (туда могут входить синонимы).

У объекта постройки смотрите **`build_on_terrain`**, **`build.cost`**, **`build.time_ticks`**, модификатор расы **`build_time_multiplier`**.

Успешный **`POST /api/buildings/place`** (упрощённо):

```json
{
  "ok": true,
  "building": {
    "id": "building-uuid",
    "building_type": "mine_t1",
    "level": 1,
    "pos": { "x": 5, "y": 12, "z": 0 },
    "ready_at_tick": 5,
    "finish_tick": 5,
    "finish_sol": 5
  },
  "build_time_ticks": 3,
  "cost": { "metal": 120, "crystal": 60, "energy": 0, "fuel": 0 },
  "builder_fleet_id": null
}
```

Пока **`ready_at_tick`** больше текущего **сола** мира, здание не даёт эффектов; при наступлении сола сервер сбрасывает **`ready_at_tick`** в **0** и шлёт **`building_ready`**. На карте: **`under_construction`**, **`remaining_ticks`**.

### Откуда брать `outpost_type` и `module_type`

- **`outpost_type`** — строка **`id`** из массива **`outposts`** в **`GET /api/balance`**.
- **`module_type`** — **`id`** из **`outpost_modules`**.
- UUID **`outpost_id`** / **`module_id`** — из **`world/state`**, окна карты или ответа **`outposts/build`**.

### Пример `GET /api/me`

```json
{
  "player_id": "uuid-string",
  "display_name": "Оператор-7",
  "planets": [
    {
      "id": "planet-uuid",
      "name": "Новый мир",
      "planet_class": "earthlike",
      "is_capital": true,
      "is_colonized": true,
      "pos": { "x": 10, "y": -4 },
      "resources": {
        "metal": 500,
        "crystal": 200,
        "energy": 100,
        "fuel": 0,
        "food": 80,
        "water": 80
      },
      "units": [{ "unit_type": "scout", "qty": 1 }]
    }
  ],
  "is_game_admin": false,
  "is_game_moderator": false
}
```

### Пример `GET /api/world/state` (фрагмент)

```json
{
  "current_tick": 42,
  "current_sol": 42,
  "player_id": "uuid",
  "player_race_id": "human",
  "race_growth": {
    "no_passive_planet_food_water": false,
    "no_passive_population_growth": false
  },
  "auto_tick_enabled": true,
  "auto_tick_interval_seconds": 5.0,
  "fleet": {
    "id": "fleet-uuid",
    "name": "Альфа-1",
    "qty": 3,
    "composition": { "scout": 2, "fighter": 1 },
    "status": "idle",
    "x": 10,
    "y": -4,
    "z": 0,
    "active_order": null
  },
  "fleets": [],
  "events": [],
  "home_planet": {
    "id": "planet-uuid",
    "population": 800,
    "max_population": 2200,
    "pos": { "x": 10, "y": -4 }
  },
  "economy": {
    "metal": 500,
    "crystal": 200,
    "energy": 100,
    "fuel": 0,
    "food": 80,
    "water": 80,
    "research_points": 12.34,
    "research_points_per_sol": 2.5,
    "net_per_sol": {
      "metal": 10,
      "crystal": -1,
      "energy": -50,
      "fuel": 1,
      "food": 0,
      "water": -2
    },
    "production_per_tick": {
      "metal": 10,
      "crystal": 2,
      "energy": -5,
      "fuel": 1,
      "food": 3,
      "water": 2
    }
  },
  "research": {
    "in_progress": false,
    "tech_id": null,
    "progress_percent": null
  }
}
```

Полная структура **`economy`**, **`influence`**, **`pending_combat_prompts`**, **`admin_dev`** (для админа) зависят от билда — ориентируйтесь на живой JSON.

### Окно карты `GET /api/world/window`

Структура: объект с ключом **`cells`** — список **строк**. Каждая строка содержит **`row`**: массив клеток с **`x`,`y`,`z`**, **`terrain`**, **`fog`** / видимость и **`objects`** (планеты, флоты, здания, форпосты — у каждого объекта есть `type` и доменные поля). Точная форма — в ответе сервера и в `WorldService.get_player_map_window`.

### Ошибки постройки (`POST /api/buildings/place`, `placement_checks`)

| `error` | Смысл (кратко) |
|---------|----------------|
| `invalid_building_type` | Строка пустая / нет в `building_aliases`. |
| `unknown_building` | Алиас есть, но определение в балансе не найдено. |
| `tech_required` | Не хватает исследований; см. **`missing_techs`**. |
| `planet_required` | Для этого типа нужна клетка планеты. |
| `wrong_foundation_terrain` | Ландшафт клетки не из `build_on_terrain`; см. **`terrain`**, **`expected`**. |
| `z_not_supported_yet` | Стройка с **`z ≠ 0`** отклонена правилом досягаемости. |
| `no_home_planet` | Нет стартовой планеты в БД. |
| `engineer_required` | Вне «района дома» без инженерного флота на клетке. |
| `inside_enemy_control_zone` | В зоне вражеского влияния. |
| `no_controlling_planet` | Не удалось связать клетку с планетой-владельцем постройки. |
| `cell_already_built` | На не-планетарной клетке уже есть здание. |
| `planet_slots_full` | Исчерпан **`build_slots_total`** планеты. |
| `no_resources` / `not_enough_resources` | См. **`need`** / **`have`**. |
| `not_enough_engineers` | На флоте-строителе не хватило инженеров. |

### Ошибки `POST /api/tech/start`

| `error` | Когда |
|---------|--------|
| `invalid_payload` | Нет строки **`tech_id`**. |
| `unknown_tech` / `tech_disabled` | Нет в балансе или выключен. |
| `tech_queue_full` | Заполнены слоты активных исследований (MVP: 1). |
| `tech_already_started` | Уже в работе или завершено. |
| `tech_prereq_missing` | см. массив **`missing`**. |
| `tech_field_data_missing` | Нет полевых данных; см. **`missing`**. |
| `not_enough_research_points` | **`need`** / **`have`**. |

### Ошибки форпостов и модулей (`/api/outposts/…`)

| `error` | Где | Смысл |
|---------|-----|--------|
| `invalid_payload` | HTTP-маршрут | Неверные типы полей в JSON. |
| `invalid_outpost_type` | build, build_checks | Тип не найден в балансе. |
| `outpost_too_close` | build, build_checks | Манхэттен до ближайшего своего форпоста < `need_distance`. |
| `z_not_supported_yet` | build, build_checks | Слой **`z ≠ 0`**. |
| `no_home_planet` | build, build_checks | Нет планеты игрока. |
| `engineer_required` | build, build_checks, модули | Вне «района дома» без инженеров на клетке. |
| `inside_enemy_control_zone` | build, build_checks | Вражеская зона контроля. |
| `not_enough_engineers` | build, install, upgrade, dismantle | См. **`need_engineers`**. |
| `cell_already_has_outpost` | build, build_checks | Уже есть активный форпост. |
| `cell_already_built` | build, build_checks | На клетке здание. |
| `tech_required` | build, upgrade, install | См. **`missing_techs`**. |
| `no_resources` / `not_enough_resources` | build, upgrade | Казна / стоимость. |
| `invalid_outpost_id` / `outpost_not_found` / `outpost_upgrade_unavailable` | upgrade, install | См. текст ошибки. |
| `invalid_module_type` | install | Тип модуля не из баланса. |
| `module_work_queue_full` | install, upgrade module | Уже есть работа **`in_progress`** по империи. |
| `outpost_slots_full` | install | Заняты все слоты модулей. |
| `invalid_module_id` / `module_not_found` / `module_busy` / `module_upgrade_unavailable` | upgrade/dismantle | См. текст ошибки. |

### Приватный чат: вход в тред

- **`POST /api/chat/private/thread/open`** — `{ "peer_id": "<uuid>", "send_read_receipts": false }`.
- **`PATCH /api/chat/private/thread/prefs`** — `{ "peer_id": "…", "send_read_receipts": true|false }`.

### Рекомендуемый цикл «агента»

1. Синхронизация: **`world/state`** (или **`me`** + узкий **`window`**).
2. Решение: координаты / тип постройки / флот с инженерами.
3. Здания: **`buildings/placement_checks`** → **`buildings/place`** или **`place_batch`**.
4. Форпосты: **`outposts/build_checks`** → **`outposts/build`**.
5. Время: **`world/tick`** или автотик.
6. Туман: **`discovery/resolve`** (с видимостью).

Источник истины по правилам — **код** и живые **`GET /api/balance`**, **`GET /api/world/state`** на вашем сервере; этот файл — карта и договорённости по HTTP.

---

## Замечание про HTML-страницы

Игровой UI (`/me`, `/register`, `/login` и т.д.) — отдельные маршруты **без** префикса `/api`. Для машинных клиентов предпочтительнее JSON API выше.
