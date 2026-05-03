# HTTP API игрока GuardStar

Краткая справка для клиентов (ботов, скриптов, UI). Все пути ниже относительно **`/api`** (blueprint зарегистрирован с префиксом `/api`).  

Пошаговые советы, **curl**, разбор ошибок постройки/техов и цикл агента — в разделе **«Расширенный учебник»** ниже на этой странице.

**Версия и актуальность:** совпадение с сервером проверяйте через `GET /api/version` (`game_version`, `balance_schema_version`). Исходники маршрутов: `server/app/routes/api/routes_*.py`.

---

## Общие правила

| Тема | Описание |
|------|----------|
| **Формат** | JSON: тела `POST`/`PATCH` — `Content-Type: application/json`. |
| **Сессия** | После `POST /api/register` или `POST /api/login` сервер выставляет **cookie-сессию Flask** (`session`). Дальнейшие запросы должны отправлять cookie (в Python удобно `requests.Session()`). |
| **401** | `{"error": "not_authenticated"}` — нет сессии или сессия сброшена. |
| **403 (аккаунт)** | Для большинства эндпоинтов отключённый аккаунт приводит к очистке сессии и ответу `{"error": "account_disabled"}` (исключения: health, ready, version, register, login, logout — см. `server/app/routes/api/__init__.py`). |
| **Координаты** | Слой `z` ограничен **−10 … 10** (где применимо на сервере). |
| **Окно карты** | Параметр `radius` для `/world/window`, `/buildings/list` клампится к **6 … 12** клеток от центра (сторона квадрата = `2 * radius + 1`). |

Типичные поля ошибок: `error` (строка), иногда `ok: false`, иногда `detail`. Успешные действия часто содержат `ok: true` и доменные поля.

---

## Проверка связи и метаданные (без логина)

Имеет смысл вызывать **до** массовых запросов или после сетевых сбоев.

### `GET /api/health`

Живость процесса (БД не проверяет).

**Пример ответа 200:**
```json
{
  "status": "ok",
  "app": "GuardStar",
  "build_id": "..."
}
```

### `GET /api/ready`

Проверка доступности БД (`SELECT 1`).

**Успех 200:** `{"status": "ready"}`  

**БД недоступна 503:** `{"status": "not_ready", "error": "db_unavailable"}`

### `GET /api/version`

Версия игры и баланса, флаги возможностей.

**Пример 200:**
```json
{
  "app": "guardstar",
  "game_version": "01.090",
  "balance_schema_version": 1,
  "balance_pack_id": "...",
  "balance_pack_name": "...",
  "features": {
    "z_layers": true,
    "procgen": true,
    "move_scout": true,
    "resource_tick": true,
    "manual_world_tick": true
  }
}
```

---

## Аутентификация и профиль

### `POST /api/register`

Создать игрока и сразу залогинить (cookie).

**Тело:**
```json
{
  "display_name": "Оператор-7",
  "race_id": "human"
}
```

**Успех 200:**
```json
{
  "player_id": "550e8400-e29b-41d4-a716-446655440000",
  "access_code": "...."
}
```

**Ошибки 400 (примеры):** `invalid_race_id`, `display_name_required`, `too_short`, `too_long`, `taken` (и др. коды валидации имени).

### `POST /api/login`

Вход по коду доступа.

**Тело:**
```json
{ "access_code": "xxxxxxxx" }
```

**Успех 200:** `{"ok": true, "player_id": "uuid"}`  

**Ошибки:** `400` — `access_code_required`; `401` — `invalid_access_code`; `403` — `account_disabled`.

### `POST /api/logout`

Сброс сессии. **Успех 200:** `{"ok": true}`

### `GET /api/me`

Обзор игрока после старта (планеты, экономика и т.д. — см. серверную сборку).

**Без авторизации:** `401` — `{"error": "not_authenticated"}`

---

## Баланс, техи, экономика, эффекты

Нужна сессия.

### `GET /api/balance`

Полная выгрузка публичного баланса: `meta`, ресурсы, расы, юниты, здания, форпости, техи и т.д. Используйте массив `buildings`, поле `id` постройки как **`building_type`** в `POST /api/buildings/place`.

**Ошибки:** `401`; `500` — `balance_not_loaded` (+ `detail`).

### `GET /api/tech/state`

Очередь исследований и запас очков науки.

Пример ключей: `current_tick`, `research_points`, `techs[]` с `tech_id`, `status`, тиками.

### `GET /api/effects/active`

Активные модификаторы игрока на текущий тик.

### `GET /api/economy/summary`

Сводка экономики. Query: `include_external_buildings` = `1`/`0` (по умолчанию учитываются внешние постройки).

### `POST /api/tech/start`

**Тело:** `{"tech_id": "some_tech"}`  

Возможные ошибки: `unknown_tech`, `tech_disabled`, конфликт слотов, нехватка RP/данных поля — смотрите тело ответа.

---

## Мир, карта, тик, снабжение

### `GET /api/world/sector?x=&y=&z=0`

Краткие данные сектора. Сессия опциональна (влияет на видимость/объекты для игрока).

### `GET /api/world/window`

Параметры: `radius`, `z`, опционально `center_x`, `center_y`.  

`reveal_fog=1` — только для **`is_game_admin`**; иначе игнорируется.

### `POST /api/discovery/resolve`

Разведка видимой клетки. **Тело:** `{"x": 0, "y": 0, "z": 0}`  

**403** возможен с `error: "sector_not_visible"`.

### `POST /api/world/tick`

Продвинуть мир на один игровой тик (нужна сессия). Ответ включает `ok: true` и поля от `process_next_tick`.

### `GET /api/world/state`

Крупное состояние для UI: текущий тик, флоты, события, настройки автотика на уровне мира и т.д.

### `POST /api/world/autotick`

**Тело:** `{"enabled": true, "interval_seconds": 5}`  

`interval_seconds` опционально, диапазон **1 … 60**. Влияет на фоновый тик-сервер (в пределах одного процесса).

### Админ: тест корсаров и нагрузки (только `is_game_admin`)

- **`POST /api/world/admin/dev/purge_bandits`** — удалить все форпосты/шахты/флоты владельца-корсара (очистка мира для замеров).
- **`POST /api/world/admin/dev/fleet_spawn_lock`** — тело `{"enabled": true|false}`: глобально запретить **новые** флоты (создание игроком, NPC-транзит, спавн корсар); движение существующих не трогается.

В **`GET /api/world/state`** у админа дополнительно приходит **`admin_dev`**: `test_block_new_fleets`, `bandit_ai_every_n_ticks` (из баланса `economy.bandit_wilderness.ai_every_n_ticks` — как часто за тик выполняется блок ИИ корсаров).

### `GET /api/supply/state?x=&y=&z=0`

Состояние системы снабжения для клетки (нужна сессия и валидные `x`,`y`).

### `POST /api/supply/hire_supplier`

**Тело:** `{"planet_id": "uuid-string"}` или `{}` — см. ответ сервера при ошибке.

---

## Юниты и флоты

### `GET /api/units/status`

Статус боевых/мирных юнитов игрока.

### `POST /api/units/move_scout`

**Тело:** `{"x": 10, "y": -3, "z": 0}`  

Успех: `{"ok": true, "status": "queued", ...}`

### `POST /api/fleets/move`

**Тело:** `{"fleet_id": "uuid", "x": 1, "y": 2, "z": 0, "force_attack": false}`  

`force_attack` опционален.

### `POST /api/fleets/cancel_order`

**Тело:** `{"fleet_id": "uuid"}`

### Прочее (все POST, JSON)

| Путь | Назначение (кратко) |
|------|---------------------|
| `/fleets/create` | Новый флот: `planet_id`, `composition` `{ "unit_id": qty }`, опционально `name` |
| `/fleets/rename` | `fleet_id`, `name` |
| `/fleets/adjust` | `fleet_id`, `deltas` |
| `/fleets/save` | `fleet_id` + `name` и/или `composition` |
| `/fleets/disband` | `fleet_id` |
| `/fleets/merge` | `target_fleet_id`, `source_fleet_id` |
| `/fleets/split` | `fleet_id`, `take` |
| `/fleets/combat_preview` | `fleet_id`, `target_x`, `target_y`, `target_z` |
| `/fleets/combat_prompt_resolve` | `order_id`, `attack` (bool) |

### `GET /api/fleets/<fleet_id>/upkeep-preview`

Превью содержания флота.

---

## Постройки и форпосты

### `GET /api/buildings/list`

Те же query, что у `/world/window` — список зданий в окне.

**Пример фрагмента 200:** `{"ok": true, "buildings": [ { "x", "y", "z", "type", "id", ... } ]}`

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

### `POST /api/buildings/placement_checks`

Проверка нескольких типов сразу: `x`, `y`, `z`, `building_types` (массив строк), опционально `fleet_id`. Ответ: `results` по каждому типу.

### `POST /api/buildings/dismantle` / `POST /api/buildings/upgrade`

**Тело:** `{"building_id": "uuid"}`

### Форпосты и модули (POST)

- `/outposts/build` — `x`, `y`, `z`, `outpost_type`, `fleet_id?`
- `/outposts/upgrade`, `/outposts/modules/install`, `/outposts/modules/upgrade`, `/outposts/modules/dismantle` — см. требования к полям в `routes_buildings_fleets_combat.py` (валидация типов как в коде).

---

## Чат (игрок)

Все запросы с сессией.

| Метод | Путь | Назначение |
|--------|------|------------|
| GET | `/chat/global` | Сообщения; query `since_id` (int, опционально) |
| POST | `/chat/global` | `{"body": "текст"}` |
| GET | `/chat/private` | `peer_id` (uuid строка), опционально `since_id` |
| POST | `/chat/private` | `{"peer_id": "...", "body": "..."}` |
| GET | `/chat/private/threads` | Список диалогов, бейджи |
| GET | `/chat/private/badge` | Сжатые счётчики |
| GET | `/chat/private/thread/meta` | `peer_id` — метаданные треда |
| POST | `/chat/private/thread/open` | открыть/настройки прочтения |
| PATCH | `/chat/private/thread/prefs` | настройки уведомлений о прочтении |
| POST | `/chat/private/thread/hide` | скрыть тред из списка |
| GET | `/chat/blocks` | Кого заблокировал игрок |
| POST | `/chat/blocks` | `{"blocked_id": "uuid"}` |
| DELETE | `/chat/blocks/<blocked_id>` | Снять блокировку |
| POST | `/chat/global/<message_id>/hide` | Скрыть своё сообщение в глобале |
| DELETE | `/chat/global/<message_id>` | Удалить своё (если разрешено логикой) |
| GET/POST | `/chat/alliance` | Альянсовый канал (если доступен игроку) |

Коды: `429` — `rate_limited`, `413` — `message_too_long`, `403` — например `blocked_peer`.

**Модерация** (`POST /chat/moderation/chat-ban`, `.../account-ban`) — только для ролей персонала; для обычного бота не документируется как «игровой» API.

---

## Минимальный сценарий «проверка → логин → карта → постройка»

1. `GET /api/health` и при необходимости `GET /api/ready`.
2. `GET /api/version` — зафиксировать `game_version`.
3. `POST /api/login` с JSON и сохранением cookie.
4. `GET /api/balance` — выбрать валидный `id` здания из `buildings`.
5. `GET /api/world/window?radius=6&z=0` — координаты своей планеты/клетки.
6. `POST /api/buildings/placement_checks` — убедиться, что тип можно поставить.
7. `POST /api/buildings/place` — постройка; при `400` разбирать `error` в JSON.
8. При необходимости `POST /api/world/tick` (или дождаться автотика).

---

## Расширенный учебник (для ботов и интеграций)

Краткого списка эндпоинтов выше **недостаточно**, если клиент должен сам восстанавливать логику после ошибок. Ниже — практика: сессия, типовые JSON, частые `error` и минимальный игровой цикл.

### Сессия / cookie

- После успешного **`POST /api/login`** или **`POST /api/register`** сервер ставит **cookie** сессии (у стандартного Flask это обычно имя `session`; точное имя и атрибуты зависят от настроек приложения и HTTPS).
- Любой последующий **`GET/POST /api/...`** должен **отправлять те же cookie**.
- **Python:** один экземпляр `requests.Session()` — логин один раз, затем все вызовы через этот объект.
- **`curl`:** файлы cookie:  
  `curl -c jar.txt -X POST …/api/login -H "Content-Type: application/json" -d "{\"access_code\":\"…\"}"`  
  затем  
  `curl -b jar.txt …/api/me`

Пример связки **`health` → `login` → `me`** (подставьте базовый URL):

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
| `GET /api/version` | Версия клиента не расходится с сервером; меняется редко. |
| `GET /api/me` или `GET /api/world/state` | Позиция дома, ресурсы, флоты, тик (`current_tick` / `current_sol`). |
| `GET /api/balance` | Справочник: допустимые **`building_type`**, стоимости, `build_on_terrain`, техмодули форпоста. |
| `GET /api/world/window` | Сетка клеток под выбор координат для стройки/разведки. |
| `POST /api/buildings/placement_checks` | Дёшево проверить кандидатов типов без списания ресурсов. |

### Откуда брать `building_type` для `POST /api/buildings/place`

Сервер нормализует строку к **нижнему регистру** и проверяет, что ключ есть среди **`aliases.building_aliases`** из баланса (в **`GET /api/balance`** это поле `aliases`, внутри — `building_aliases`). Обычно ключ **совпадает** с **`id`** соответствующего объекта в массиве `buildings`, но источником истины для API считайте **именно `building_aliases`** (туда могут входить синонимы/алиасы).

У объекта постройки в балансе смотрите также **`build_on_terrain`** (где можно строить) и блок **`build.cost`**.

Успешный **`POST /api/buildings/place`** (упрощённо):

```json
{
  "ok": true,
  "building": {
    "id": "building-uuid",
    "building_type": "mine_t1",
    "level": 1,
    "pos": { "x": 5, "y": 12, "z": 0 }
  },
  "cost": { "metal": 120, "crystal": 60, "energy": 0, "fuel": 0 },
  "builder_fleet_id": null
}
```

Если **`builder_fleet_id` не null**, инженеры на этом флоте могли быть расходуются (см. `not_enough_engineers`).

### Пример `GET /api/me`

Если домашняя планета уже создана:

```json
{
  "player_id": "uuid-string",
  "display_name": "Оператор-7",
  "planets": [
    {
      "id": "planet-uuid",
      "name": "Новый мир",
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

Если планеты ещё нет (редкий промежуток), возможен массив `planets`: `[]` с теми же ключами профиля.

### Пример `GET /api/world/state` (фрагмент)

Большой ответ; для бота важнее всего:

- **`current_tick` / `current_sol`** — «время» мира.
- **`economy`** — запасы дома, **`net_per_sol`** (чистый приток/расход по империи за сол, как в `GET /api/economy/summary`) и часто **производство за тик** (`production_per_tick` / `_per_sol` — синонимы чисел).
- **`fleets`**, **`fleet`** — флоты с `composition` по типам юнитов (`scout`, `engineer`, …), позиции, `active_order`.
- **`events`** — последние события (бой, нехватка ресурсов, постройки); каждое имеет **`type`**, **`message`**, **`payload`**.
- Поля **`auto_tick_*`** и наложения вроде **`balance_error`** — диагностика сервера.

```json
{
  "current_tick": 42,
  "current_sol": 42,
  "player_id": "uuid",
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
  "home_planet": { "population": 800, "max_population": 2200, "pos": { "x": 10, "y": -4 } },
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
  }
}
```

Полная структура **`economy`** и блоки **`influence`**, **`pending_combat_prompts`** зависят от билда; смотрите фактический JSON.

### Окно карты `GET /api/world/window`

Структура ориентировочно: объект с ключом **`cells`** — список **строк**. Каждая строка содержит **`row`**: массив клеток с **`x`,`y`,`z`**, возможным **`terrain`**, **`fog`** / видимость и массивом **`objects`** (планеты, флоты, здания и т.д. с типом `type`). Точную форму смотрите в ответе сервера на вашем билде и при необходимости в коде сборки окна во `WorldService`.

### Ошибки постройки (`POST /api/buildings/place`, `placement_checks`)

Ниже — типичные значения **`error`** (тело JSON, статус **`400`**). Не считайте список исчерпывающим: при расширении правил возможны новые коды.

| `error` | Смысл (кратко) |
|---------|----------------|
| `invalid_building_type` | Строка пустая / нет в `building_aliases`. |
| `unknown_building` | Алиас есть, но определение в балансе не найдено. |
| `tech_required` | Не хватает исследований; см. **`missing_techs`**. |
| `planet_required` | Для этого типа нужна клетка планеты. |
| `wrong_foundation_terrain` | Ландшафт клетки не из `build_on_terrain`; смотрите **`terrain`**, **`expected`**. |
| `z_not_supported_yet` | Сейчас стройка с **`z ≠ 0`** отклоняется правилом досягаемости. |
| `no_home_planet` | У игрока нет стартовой планеты в БД. |
| `engineer_required` | Клетка вне «района дома» (манхэттен ≤ 3 от своих планет) без инженерного флота на клетке. |
| `inside_enemy_control_zone` | В зоне вражеского влияния. |
| `no_controlling_planet` | Не удалось связать клетку с планетой-владельцем постройки. |
| `cell_already_built` | На этой не-планетарной клетке уже есть здание. |
| `planet_slots_full` | Исчерпан общий **`build_slots_total`** планеты. |
| `no_resources` / `not_enough_resources` | Нет строки склада или мало ресурсов; см. **`need`** / **`have`**. |
| `not_enough_engineers` | Полевое строительство: на флоте-строителе не хватило инженеров. |

### Ошибки `POST /api/tech/start`

Сводка кодов **`400`** с **`ok: false`** (частые):

| `error` | Когда |
|---------|--------|
| `invalid_payload` | Нет строки **`tech_id`**. |
| `unknown_tech` / `tech_disabled` | Нет в балансе или выключен. |
| `tech_queue_full` | Уже активное исследование (**MVP**: один слот). |
| `tech_already_started` | Уже в работе или завершено. |
| `tech_prereq_missing` | см. массив **`missing`**. |
| `tech_field_data_missing` | Нет нужных данных поля (**`missing`**: виды полевых данных). |
| `not_enough_research_points` | **`need`** / **`have`**. |

### Форпосты и модули (тела запросов)

| Эндпоинт | JSON-тело |
|----------|-----------|
| `POST /api/outposts/build` | `{ "x", "y", "z", "outpost_type", "fleet_id"? }` |
| `POST /api/outposts/upgrade` | `{ "outpost_id" }` |
| `POST /api/outposts/modules/install` | `{ "outpost_id", "module_type" }` |
| `POST /api/outposts/modules/upgrade` | `{ "module_id" }` |
| `POST /api/outposts/modules/dismantle` | `{ "module_id" }` |

Идентификаторы и допустимые строки типов берите из **`GET /api/balance`** (`outposts`, `outpost_modules`).

### Приватный чат: вход в тред

- **`POST /api/chat/private/thread/open`** — тело: `{ "peer_id": "<uuid>", "send_read_receipts": false }`.
- **`PATCH /api/chat/private/thread/prefs`** — `{ "peer_id": "…", "send_read_receipts": true|false }`.

### Рекомендуемый цикл «агента»

1. Синхронизация: **`world/state`** (или **`me`** + узкий **`window`**).
2. Решение (в коде или LLM): целевые координаты / тип постройки / флот.
3. **`placement_checks`** → при `ok` в нужной строке **`results`** — **`place`**.
4. Если нужно изменить экономику времени — **`world/tick`** или ждать **автотик**.
5. Разведка занятой клетки — **`discovery/resolve`** (с учётом видимости; иначе `sector_not_visible`).

Изменения игровых правил со временем делают **источником истины** всё-таки **код** и живой **`GET /api/balance`**; этот файл — карта местности, не замена эксперимента на вашем сервере.

---

## Замечание про HTML-страницы

Игровой UI (`/me`, `/register`, `/login` и т.д.) — отдельные маршруты **без** префикса `/api`. Для машинных клиентов предпочтительнее JSON API выше.
