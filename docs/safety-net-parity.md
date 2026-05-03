# Паритет `dev_schema_safety_net` и прод без `GUARDSTAR_DB_SAFETY_NET`

Источник поведения safety-net: `server/app/db/dev_schema_safety_net.py` (`apply_dev_schema_safety_net`, только при `GUARDSTAR_DB_SAFETY_NET=true`).

Цель: на БД, поднятой **только** линейной цепочкой Alembic до `20260516_000027` и ниже, не должно падать то, что safety-net «догоняет». Это закрывает миграцией **`20260517_000028`**: в начале `upgrade` — объекты вроде `admin_config` / `fleet_ships` / `buildings` / `game_clock`; затем **`_apply_safety_net_parity_sql`** (идемпотентный DDL из этого чеклиста); для **`fleets.name`** при первом добавлении колонки — бэкафл имён как в safety-net (`fleet_display_name_for_index`). Плюс уже существующие ревизии в ветке `main`.

## Замечание по индексам `explored_sectors`

Раньше `CREATE INDEX … explored_sectors` ошибочно выполнялись из ветки `else` для **`outpost_modules`** (после правки — в секции **`explored_sectors`** + обновление `inspect` после первого `CREATE TABLE explored_sectors`).

## Сводная таблица

| Объект в safety-net | Суть | Где в проде без safety-net |
|---------------------|------|-----------------------------|
| `planets` колонки population, max_population, planet_class, build_slots_total, supplier_count + `ix_planets_planet_class` | Догонка планет | Ветки/ранние ревизии + **`028` parity** |
| `fleets` energy, max_energy, hunt_target_fleet_id, patrol_outpost_id, strike_origin_outpost_id, bandit_hunt_announced | Энергия/патруль/удар | Alembic ветки + **`028` parity** |
| `fleets.name` + бэкафл имён по слоту | Имя флота | **`028`** |
| `unit_orders` from_x, from_y, from_z | Координаты старта приказа | **`028` parity** |
| `events` таблица + индексы | Лента событий | **`028` parity** |
| `fleet_orders` таблица + force_attack, combat_prompt_expires_at | Очередь приказов флота | **`028` parity** |
| `explored_sectors` таблица + discovery_* + индексы | Туман войны / находки | Ветка `20260430` + **`028` parity** |
| `outposts` / `outpost_modules` | Аванпосты | Ревизии outpost + **`028` parity** |
| `game_clock` auto_tick_* | Автотик | **`028`** |
| `resources` fuel, food, water | Экономика | **`028`** |
| `world_state` таблица + admin_*, test_*, spawn + **economy_base_food_per_sol / economy_base_water_per_sol** | Глобальные флаги и база еды/воды | **`028` parity** + **`20260518_000029`** |
| `admin_config` | Админка | **`028`** |
| `buildings` полная таблица или planet_id / capture_* | Захват / привязка к планете | **`028`** + **`028` parity** для старых таблиц без колонок |
| `players` race_id, feedback_audited, research_points | Регистрация / фидбек / RP | **`028`** + **`028` parity** |
| `fleet_ships` + backfill из `fleets` | Нормализация состава | **`028`** |
| `player_techs` + индекс по status (если нужен) | Исследования | **`028`** + **`028` parity** |
| `player_effects` | Эффекты игрока | **`028` parity** |
| `feedback_playtest_api_logs` | Логи плейтест API | **`028` parity** |
| `chat_messages.read_receipt_at` | Прочтение ЛС | `20260510_000021` + **`028` parity** |
| `private_chat_peer_prefs` | Настройки пары в ЛС | `20260510_000021` + **`028` parity** |

## Операции

- **Прод / dev без safety-net:** `alembic upgrade head` (включая `028`).
- **Временная догонка на старой БД:** включить `GUARDSTAR_DB_SAFETY_NET=true` на один старт приложения (осторожно: обёрнуто в `try/except` и может скрыть ошибки) — предпочтительнее довести миграции.

## Downgrade `028`

Часть колонок из блока parity **намеренно не откатывается** в `downgrade` (как и раньше для крупных объектов): откат затронет только объекты, которые изначально создавались в первой части `028`.
