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
| **Окно карты** | Параметр `radius` для `/world/window`, `/buildings/list` клампится к **6 … 12** (шаги гекса от центра); в ответе окна поле **`topology`: `"hex"`**, клетки — **диск** в осевых координатах `x`,`y` (как `q`,`r`). |

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

Крупное состояние для UI: текущий **сол** мира (`current_sol` / `current_tick`), флоты, события, настройки автотика на уровне мира и т.д. Дополнительно: **`player_race_id`**, **`race_growth`**: `{ "no_passive_planet_food_water", "no_passive_population_growth" }` (флаги из `races.json` для текущей расы); **`home_planet.id`** — UUID домашней планеты. Блок **`research`**: `{ "in_progress": bool, "tech_id": string|null, "progress_percent": int|null }` — для HUD науки: при активном исследовании в топбаре у RP может показываться **(N%)** готовности текущего теха; без очереди — только визуальный «простой» чипа.

### `POST /api/world/recruit_population`

Явный набор населения на **своей** колонии — только для рас с **`no_passive_population_growth`** в балансе (напр. `silicon`). **Тело:** `{ "planet_id": "<uuid>", "amount": <int> }` (лимит за запрос из `economy.citizen_recruit.max_population_per_request`). Стоимость за единицу населения: `economy.citizen_recruit` (`metal_per_pop`, `crystal_per_pop`, `food_per_pop`, `water_per_pop`). Ошибки: `recruit_not_available_for_race` (400), `planet_not_owned` (403), `not_enough_resources`, `population_cap`.

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

### Баланс юнитов (`GET /api/balance`): обзор с клетки, корпус, разблокировки

- **`map_vision_radius_cells`** (необязательное поле в записи юнита в `units.json`, при загрузке баланса допускаются только целые **0…6**): вклад типа корабля в **пассивный обзор** (туман войны) с клетки, где стоит флот. Для **смешанного** состава флота сервер берёт **максимум** по присутствующим типам. Если поля нет, для логического типа **`scout`** сохраняется прежний эквивалент **2**, для остальных — **1** (обратная совместимость).
- **`fleet_energy_pool_bonus_per_ship`** и **`fleet_travel_fuel_flat_discount_per_ship`** (необязательные целые **0…500** в `units.json`): на каждый такой корабль в составе увеличивается **потолок энергии на борту** всего флота и уменьшается **суммарное топливо** на один перелёт (скидка не опускает расход ниже **1**, если базовый расход был больше нуля). Суммарный бонус энергии и скидка топлива по всему составу ограничены сервером сверху.
- **`fleet_composition_allowed`** (необязательное **bool** в `units.json`): при **`false`** тип не входит в состав игрока — сервер отбрасывает его из `composition` / `deltas` / `take` (с возвратом ресурсов на склад столицы по тем же правилам, что и при уменьшении числа кораблей). Радиус имперского снабжения по найму **снабженцев** на планете (`POST /api/supply/hire_supplier`) от этого не зависит.
- **Ось корпуса** в техах: `tech_hull_micro` … `tech_hull_heavy` (часть узлов может быть с `enabled: false` как резерв дерева). Разблокировка составных кораблей — через **`prereq_tech`** у юнита: должны быть выполнены **все** перечисленные техи (например средний корпус + сенсоры).
- **Utility-флоты (дорожная карта):** тот же шаблон «уровень корпуса + подсистема» планируется для ECM, relay, mobile refinery, repair tender, носителя сенсорных платформ и т.п. — отдельные `unit_id` и флаги поведения по мере появления механик.
- **Бой без лишних %%:** новые корабельные проекты в техах с **`effects: {}`**; глобальные `combat_*_multiplier` из старых тех по-прежнему могут влиять на расчёт боя — отдельные **профили оружия** (`weapon_profile` / `damage_type`) для ветвления урона зарезервированы на будущее (лазер vs баллистика и т.д.), в текущем билде поля могут отсутствовать.

### `GET /api/units/status`

Статус боевых/мирных юнитов игрока.

### `POST /api/units/move_scout`

**Тело:** `{"x": 10, "y": -3, "z": 0}`  

Успех: `{"ok": true, "status": "queued", ...}`

### `POST /api/fleets/move`

**Тело:** `{"fleet_id": "uuid", "x": 1, "y": 2, "z": 0, "force_attack": false}`  

`force_attack` опционален. Цель не может быть клеткой планеты (`target_cell_has_planet`); флот стоит только на соседних клетках.

### `POST /api/fleets/cancel_order`

**Тело:** `{"fleet_id": "uuid"}`

### Прочее (все POST, JSON)

| Путь | Назначение (кратко) |
|------|---------------------|
| `/fleets/create` | Новый флот: `planet_id`, `composition` с логическими ключами из `unit_aliases` (кроме типов с `fleet_composition_allowed: false` в балансе — например **снабженец** только через планету), опционально `name` |
| `/fleets/rename` | `fleet_id`, `name` |
| `/fleets/adjust` | `fleet_id`, `deltas` |
| `/fleets/save` | `fleet_id` + `name` и/или `composition` |
| `/fleets/disband` | `fleet_id` |
| `/fleets/merge` | `target_fleet_id`, `source_fleet_id` |
| `/fleets/split` | `fleet_id`, `take` |
| `/fleets/combat_preview` | `fleet_id`, `target_x`, `target_y`, `target_z` |
| `/fleets/combat_prompt_resolve` | `order_id`, `attack` (bool) |
| `/intel/scan_fleet` | Скан чужого флота: `scanner_fleet_id`, `target_fleet_id` (см. ниже) |

### `POST /api/intel/scan_fleet`

**Тело:** `{"scanner_fleet_id": "uuid", "target_fleet_id": "uuid"}`.

- Сканер — ваш флот **без** активного приказа (`queued` / `in_progress` / `pending_combat`).
- Цель — **чужой** флот; та же плоскость `z`; расстояние по гексу между центрами ≤ `intel_scan.max_range_hex` в [`server/data/balance/economy.json`](server/data/balance/economy.json) (по умолчанию 1).
- Стоимость: **RP** игрока (`intel_scan.rp_cost`, по умолчанию 3). Если у владельца цели в завершённых техах есть `intel_scan.defender_blocking_tech` (по умолчанию `tech_fleet_doctrine_1`), возвращается `ok: false`, `error: "intel_blocked"` — **RP не списываются**; в лог попадает событие `intel_blocked`.
- При успехе: `composition` (словарь логических типов → количество), `rp_spent`, `research_points_after`; события **`intel_scan_success`** (сканеру) и **`intel_scanned`** (владельцу цели).
- **Связь с разведкой:** пассивный радиус с флота (`map_vision_radius_cells`, см. выше) задаёт базовый слой «что видно в тумане» без RP; активный скан — отдельный шаг. В перспективе параметры сканов (дальность, сигнатуры, **detection strength**) можно увязать с классом разведчика и подсистемами сенсоров, не дублируя ветки глобальных процентов.

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

**Успех 200:** `{"ok": true, "results": { "<тип>": { ...как у build/check одного типа... } } }`  
Для каждого ключа типа значение либо **`{"ok": true}`**, либо **`{"ok": false, "error": "...", ...}`** — тот же набор полей, что вернёт **`POST /api/outposts/build`** при отказе (включая **`need`** / **`have`** при **`not_enough_resources`**, **`need_distance`** / **`nearest`** при **`outpost_too_close`** и т.д.).

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
| GET | `/chat/alliance` | Сообщения альянса: query **`alliance_id`** (uuid), опционально **`since_id`** |
| POST | `/chat/alliance` | `{"alliance_id": "<uuid>", "body": "..."}` — только для членов этого альянса |

Коды: `429` — `rate_limited`, `413` — `message_too_long`, `403` — например `blocked_peer`.

**Модерация** (`POST /chat/moderation/chat-ban`, `.../account-ban`) — только для ролей персонала; для обычного бота не документируется как «игровой» API.

---

## Альянсы (фаза 1)

Все запросы с сессией. Экономика и снабжение остаются **персональными**; альянс даёт тег, код приглашения, чат, флаг **«союзник»** на карте (см. объекты флота в окне карты) и превью **совместного влияния** в клетке (сумма `control_value` членов с капом из баланса `economy.alliance.influence_cell_cap`).

| Метод | Путь | Назначение |
|--------|------|------------|
| POST | `/alliance/create` | Тело **`display_name`** (или `name`) и **`tag`** (2–8 символов `A–Z`/`0–9`); создатель — **лидер**; ответ содержит **`join_code`**. |
| POST | `/alliance/join` | Тело **`join_code`** (или `code`) — вступление; ошибки: `already_in_alliance`, `alliance_not_found`, `alliance_full`. |
| POST | `/alliance/leave` | Выход; если игрок — **лидер**, альянс **распускается** (`disbanded: true`). |
| GET | `/alliance/me` | `{ "ok": true, "alliance": null }` вне альянса; иначе `id`, `display_name`, `tag`, **`join_code` только у лидера**, `my_role`, **`members`**. |
| GET | `/alliance/influence_at` | Query **`x`**, **`y`**, опционально **`z`** — для члена альянса: `sum`, `capped`, `cap`, `alliance_id`; `403` если не в альянсе. |

---

## Минимальный сценарий «проверка → логин → карта → постройка»

1. `GET /api/health` и при необходимости `GET /api/ready`.
2. `GET /api/version` — зафиксировать `game_version`.
3. `POST /api/login` с JSON и сохранением cookie.
4. `GET /api/balance` — валидные типы: `buildings` / `aliases.building_aliases`, при форпостах — массив **`outposts`**.
5. `GET /api/world/window?radius=6&z=0` — координаты своей планеты/клетки.
6. `POST /api/buildings/placement_checks` или `POST /api/outposts/build_checks` — проверка без списания ресурсов.
7. `POST /api/buildings/place` / **`place_batch`** или **`POST /api/outposts/build`** — постройка; при `400` разбирать `error` и дополнительные поля (`need`/`have`, `missing_techs`, …).
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
| `GET /api/me` или `GET /api/world/state` | Позиция дома, ресурсы, флоты, номер текущего **сола** в мире (`current_tick` / `current_sol` — одно и то же число). |
| `GET /api/balance` | Справочник: **`building_type`** (через `aliases.building_aliases`), массивы **`outposts`** и **`outpost_modules`** (поля **`id`** / типы для API), стоимости, `build_on_terrain`, ветки **`upgrade`**, **`vision`**, слоты. |
| `GET /api/world/window` | Сетка клеток под выбор координат для стройки/разведки. |
| `POST /api/buildings/placement_checks` | Дёшево проверить кандидатов типов без списания ресурсов. |
| `POST /api/outposts/build_checks` | То же для типов форпостов перед **`/outposts/build`**. |

### Откуда брать `building_type` для `POST /api/buildings/place`

Сервер нормализует строку к **нижнему регистру** и проверяет, что ключ есть среди **`aliases.building_aliases`** из баланса (в **`GET /api/balance`** это поле `aliases`, внутри — `building_aliases`). Обычно ключ **совпадает** с **`id`** соответствующего объекта в массиве `buildings`, но источником истины для API считайте **именно `building_aliases`** (туда могут входить синонимы/алиасы).

У объекта постройки в балансе смотрите также **`build_on_terrain`** (где можно строить) и блок **`build.cost`**, а также **`build.time_ticks`** — сколько **солов** (шагов календаря мира) длится ввод постройки в строй; умножается на **`build_time_multiplier`** расы из баланса.

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

Пока **`ready_at_tick`** здания **больше** текущего номера **сола** в мире (`current_tick` / `current_sol`), оно **не даёт** игровых эффектов (производство, лимиты населения и т.д.); когда календарь доходит до этого сола, сервер сбрасывает **`ready_at_tick`** в **0** и шлёт событие **`building_ready`**. На карте и в **`GET /api/world/sector`** у объекта здания: **`under_construction`**, **`remaining_ticks`** (остаток в тех же «солах»). У своей планеты в **`details.build`**: **`queue`** (незавершённые), **`active`**, **`current_tick`**.

`finish_tick` / `finish_sol` в ответе **place** — то же число, что **`ready_at_tick`**: номер **сола**, к которому здание будет введено в строй (поля с суффиксом `_tick` в JSON — наследие имён, смысл для игрока — сол).

Если **`builder_fleet_id` не null**, инженеры на этом флоте могли быть расходуются (см. `not_enough_engineers`).

### Откуда брать `outpost_type` и `module_type`

- **`outpost_type`** для **`/outposts/build`** и элементов **`outpost_types`** в **`build_checks`** — строка **`id`** (или эквивалентный ключ из баланса), как задано в массиве **`outposts`** ответа **`GET /api/balance`**. Сервер ищет определение через внутренний резолвер типов; при неизвестной строке — **`invalid_outpost_type`**.
- **`module_type`** для **`/outposts/modules/install`** — **`id`** из массива **`outpost_modules`** в том же **`balance`**. Неизвестный тип — **`invalid_module_type`**.
- UUID **`outpost_id`** / **`module_id`** берите из **`world/state`**, окна **`world/window`** (объекты на клетке) или из ответа успешного **`outposts/build`** (`outpost.id`); после установки модуля **`module_id`** появляется в детализации форпоста в состоянии мира.

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

Если планеты ещё нет (редкий промежуток), возможен массив `planets`: `[]` с теми же ключами профиля.

### Колонизация планеты

`POST /api/planets/colonize`

Тело:

```json
{ "planet_id": "uuid", "fleet_id": "uuid" }
```

Условия (MVP):

- Планета существует и принадлежит нейтрали (ещё не колонизирована).
- Флот игрока стоит **на клетке планеты или в одной из шести соседних по гексу** (расстояние 0–1 от `(pos_x,pos_y)` планеты, `z=0`) и содержит юнит с флагом колонизации (см. `units.json`, алиас `colonizer`).
- У игрока выполнены требования технологий для `planet_class` (по `planet_types.json`) и хватает ресурсов на столице.

Успех:

```json
{ "ok": true, "planet_id": "uuid" }
```

### Пример `GET /api/world/state` (фрагмент)

Большой ответ; для бота важнее всего:

- **`current_tick` / `current_sol`** — «время» мира.
- **`economy`** — запасы дома, **`net_per_sol`** (чистый приток/расход по империи за сол, как в `GET /api/economy/summary`) и часто **производство за тик** (`production_per_tick` / `_per_sol` — синонимы чисел).
- **`fleets`**, **`fleet`** — флоты с `composition` по типам юнитов (`scout`, `engineer`, …), позиции, `active_order`.
- **`events`** — последние события (бой, нехватка ресурсов, постройки); каждое имеет **`type`**, **`message`**, **`payload`**.
- **`player_race_id`**, **`race_growth`** — раса и флаги «без пассивной еды/воды с планеты», «без пассивного роста населения» (см. `races.json`).
- Поля **`auto_tick_*`** (в т.ч. `auto_tick_last_run_at` / `auto_tick_last_tick` после включения автотика сервер делает **один сол сразу**, затем — каждые `auto_tick_interval_seconds`) и наложения вроде **`balance_error`** — диагностика сервера.

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

### Ошибки форпостов и модулей (`/api/outposts/…`)

Общие для **`build`** и **`build_checks`** (где применимо): те же коды, что возвращает **`_can_build_at`**, плюс специфичные для форпоста. Для модулей — отдельные коды внизу таблицы.

| `error` | Где | Смысл |
|---------|-----|--------|
| `invalid_payload` | HTTP-маршрут | Неверные типы полей в JSON (координаты не int, нет строки типа и т.д.). |
| `invalid_outpost_type` | build, build_checks | Тип не найден в балансе. |
| `outpost_too_close` | build, build_checks | До ближайшего своего форпоста на слое **`z`** меньше **`need_distance`** (Манхэттен); см. **`nearest`**, **`nearest_outpost`**. |
| `z_not_supported_yet` | build, build_checks | Слой **`z ≠ 0`** для этой логики не поддержан. |
| `no_home_planet` | build, build_checks | Нет планеты игрока. |
| `engineer_required` | build, build_checks, модули | Вне «района дома» без своего флота с инженерами на клетке форпоста. |
| `inside_enemy_control_zone` | build, build_checks | Клетка в зоне вражеского контроля. |
| `not_enough_engineers` | build, build_checks, install, upgrade, dismantle | Недостаточно инженеров на флоте; см. **`need_engineers`**. |
| `cell_already_has_outpost` | build, build_checks | Уже есть активный форпост. |
| `cell_already_built` | build, build_checks | На клетке уже стоит здание. |
| `tech_required` | build, build_checks, upgrade, install, upgrade module | Не выполнены техи; см. **`missing_techs`**, **`required_techs`**. |
| `no_resources` | build, build_checks, upgrade | Нет строки ресурсов домашней планеты. |
| `not_enough_resources` | build, build_checks, upgrade | Мало металла/кристалла/энергии/топлива; у **build** / **checks** обычно есть **`need`** и **`have`**. |
| `invalid_outpost_id` | upgrade, install | Не UUID. |
| `outpost_not_found` | upgrade, install, dismantle (через модуль) | Чужой или несуществующий форпост. |
| `outpost_upgrade_unavailable` | upgrade | В балансе нет ветки **`upgrade.to`**. |
| `invalid_module_type` | install | Тип модуля не из баланса. |
| `module_work_queue_full` | install, upgrade module | Уже есть другой модуль империи в **`in_progress`**. |
| `outpost_slots_full` | install | Все слоты **`module_slots_total`** заняты. |
| `invalid_module_id` | upgrade module, dismantle | Не UUID. |
| `module_not_found` | upgrade module, dismantle | Нет строки модуля или не ваш. |
| `module_busy` | upgrade module, dismantle | Модуль не в **`active`** (например, ещё строится). |
| `module_upgrade_unavailable` | upgrade module | Нет ветки улучшения в балансе для этого типа. |

Тела **`POST`** для форпостов и модулей описаны в разделе **«Постройки и форпосты»** выше.

### Приватный чат: вход в тред

- **`POST /api/chat/private/thread/open`** — тело: `{ "peer_id": "<uuid>", "send_read_receipts": false }`.
- **`PATCH /api/chat/private/thread/prefs`** — `{ "peer_id": "…", "send_read_receipts": true|false }`.

### Рекомендуемый цикл «агента»

1. Синхронизация: **`world/state`** (или **`me`** + узкий **`window`**).
2. Решение (в коде или LLM): целевые координаты / тип постройки или форпоста / флот с инженерами.
3. Для **зданий**: **`buildings/placement_checks`** → при **`ok`** в **`results`** — **`buildings/place`** (или **`place_batch`**).
4. Для **форпостов**: **`outposts/build_checks`** → при **`ok`** для выбранного типа — **`outposts/build`** (тот же **`fleet_id`**, что в проверке).
5. Если нужно изменить экономику времени — **`world/tick`** или ждать **автотик**.
6. Разведка занятой клетки — **`discovery/resolve`** (с учётом видимости; иначе `sector_not_visible`).

Изменения игровых правил со временем делают **источником истины** всё-таки **код** и живой **`GET /api/balance`**; этот файл — карта местности, не замена эксперимента на вашем сервере.

---

## Замечание про HTML-страницы

Игровой UI (`/me`, `/register`, `/login` и т.д.) — отдельные маршруты **без** префикса `/api`. Для машинных клиентов предпочтительнее JSON API выше.
