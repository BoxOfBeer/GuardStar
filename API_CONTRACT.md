# GuardStar API Contract (MVP)

Ниже описано **фактическое** текущее поведение API.

## POST /api/register
- **Метод:** `POST`
- **Request body (JSON):**
  ```json
  { "display_name": "Pilot" }
  ```
- **Успех 200:**
  ```json
  { "player_id": "<uuid>", "access_code": "<32-char-code>" }
  ```
- **Ошибки:**
  - `400` → `{ "error": "display_name_required" }`

## POST /api/login
- **Метод:** `POST`
- **Request body (JSON):**
  ```json
  { "access_code": "<32-char-code>" }
  ```
- **Успех 200:**
  ```json
  { "ok": true, "player_id": "<uuid>" }
  ```
- **Ошибки:**
  - `400` → `{ "error": "access_code_required" }`
  - `401` → `{ "error": "invalid_access_code" }`

## GET /api/me
- **Метод:** `GET`
- **Request body:** отсутствует
- **Успех 200:**
  ```json
  {
    "player_id": "<uuid>",
    "planets": [
      {
        "id": "<uuid>",
        "name": "Terra Prime",
        "pos": { "x": 0, "y": 0 },
        "resources": { "metal": 500, "crystal": 250, "energy": 100, "fuel": 100, "food": 120, "water": 120 },
        "units": [
          { "unit_type": "fighter", "qty": 1 },
          { "unit_type": "scout", "qty": 5 }
        ]
      }
    ]
  }
  ```
- **Ошибки:**
  - `401` → `{ "error": "not_authenticated" }`

## GET /api/world/window
- **Метод:** `GET`
- **Query params:**
  - `radius` (опционально, clamp `1..10`, default `4`)
  - `z` (опционально, clamp `-10..10`, default `0`)
- **Успех 200:**
  ```json
  {
    "center": { "x": 0, "y": 0 },
    "radius": 4,
    "z": 0,
    "cells": [
      {
        "y": -4,
        "row": [
          {
            "x": -4,
            "y": -4,
            "z": 0,
            "objects": [],
            "terrain": "empty",
            "glyph": ".",
            "flags": { "is_center": false, "has_objects": false }
          }
        ]
      }
    ]
  }
  ```
- **Ошибки:**
  - `401` → `{ "error": "not_authenticated" }`

## POST /api/units/move_scout
- **Метод:** `POST`
- **Request body (JSON):**
  ```json
  { "x": 1, "y": 0, "z": 0 }
  ```
- **Успех 200:**
  ```json
  {
    "ok": true,
    "status": "queued",
    "order_id": "<uuid>",
    "fleet_id": "<uuid>",
    "from": { "x": 0, "y": 0, "z": 0 },
    "target": { "x": 1, "y": 0, "z": 0 },
    "qty": 1,
    "distance": 1,
    "travel_ticks": 1,
    "travel_sols": 1,
    "start_tick": 1,
    "start_sol": 1,
    "finish_tick": 1,
    "finish_sol": 1,
    "fuel_cost": 0
  }
  ```
- **Ошибки:**
  - `401` → `{ "error": "not_authenticated" }`
  - `400` → `{ "error": "invalid_coords" }`
  - `400` → `{ "ok": false, "error": "no_home_planet" }`
  - `400` → `{ "ok": false, "error": "z_not_supported_yet" }`
  - `400` → `{ "ok": false, "error": "not_enough_scouts" }`
  - `400` → `{ "ok": false, "error": "active_order_exists" }`

## Плейтест-аудит (сервер)

Для аккаунтов с флагом `players.feedback_audited=true` (включается в админке `/admin/accounts`) сервер записывает в таблицу `feedback_playtest_api_logs` **только мутации** над `/api/*`: `POST`, `PUT`, `PATCH`, `DELETE` (метод, путь, усечённое тело запроса, код ответа, длительность). Запросы к `/api/login` и `/api/register` не сохраняют реальное тело. Частые GET (карта, опрос состояния) **не пишутся**, чтобы не зашумлять журнал.

## GET /api/version
- **Метод:** `GET`
- **Request body:** отсутствует
- **Успех 200:**
  ```json
  {
    "app": "guardstar",
    "game_version": "01.019",
    "balance_schema_version": 1,
    "balance_pack_id": "<string-or-null>",
    "balance_pack_name": "<string-or-null>",
    "features": {
      "z_layers": true,
      "procgen": true,
      "move_scout": true,
      "resource_tick": true
    }
  }
  ```
- **Ошибки:** отсутствуют в текущей реализации.

## GET /api/tech/state
- **Метод:** `GET`
- **Успех 200:**
  ```json
  {
    "ok": true,
    "current_tick": 0,
    "current_sol": 0,
    "techs": [
      {
        "tech_id": "tech_example",
        "status": "none|in_progress|done",
        "started_tick": 0,
        "finish_tick": 0,
        "remaining_ticks": null
      }
    ]
  }
  ```
- **Ошибки:** `401` → `{ "error": "not_authenticated" }`

## POST /api/tech/start
- **Метод:** `POST`
- **Request body (JSON):** `{ "tech_id": "tech_example" }`
- **Успех 200:** помимо базовых полей могут приходить модификаторы от `player_effects` (руины/аномалии):
  ```json
  {
    "ok": true,
    "tech_id": "tech_example",
    "status": "in_progress",
    "started_tick": 1,
    "finish_tick": 12,
    "research_time_multiplier": 1.0,
    "research_ticks_base": 10,
    "residual_time_ticks": 6,
    "research_ticks_adjusted": 10,
    "research_points_spent": 24.0,
    "research_points_after": 0.0,
    "blueprint_cache_consumed": false,
    "blueprint_discount": null
  }
  ```
  - Списание **`research_points_cost`** из записи технологии в балансе; длительность идёт по **`residual_time_ticks`** (после бустов — `research_ticks_adjusted`).
  - `research_ticks_adjusted` — остаток сол после буста `research_speed_boost` (если активен).
  - `blueprint_cache_consumed` / `blueprint_discount` — одноразовый кэш чертежей при старте (скидки в payload для UI/будущей экономики).
  - `field_data_required` / `field_data_consumed` — полевые данные, которые требуются/списываются для части технологий (см. `field_data_requirements` в balance tech).
  - Ошибка слотов (MVP): если уже идёт исследование, вернётся:
    - `400` → `{ "ok": false, "error": "tech_queue_full", "active": 1, "slots": 1 }`
  - Недостаточно RP:
    - `400` → `{ "ok": false, "error": "not_enough_research_points", "need": 24.0, "have": 0.0 }`

## POST /api/buildings/upgrade
- **Метод:** `POST`
- **Body:** `{ "building_id": "<uuid>" }` — постройка на планете игрока, у типа есть блок `upgrade` в балансе.
- **Успех:** `{ "ok": true, ... }`
- **Ошибки:** `building_upgrade_unavailable`, `tech_required`, `not_enough_resources`, `planet_type_cap`, и др.

## POST /api/discovery/resolve
- **Метод:** `POST`
- **Body:** `{ "x": 0, "y": 0, "z": 0 }` — явное исследование руин/аномалии в видимом секторе (одноразово на сектор через `discovery_done`).
- **Успех / ошибки:** см. сообщения вида `{ "ok": false, "error": "nothing_to_discover" }`.

## GET /api/economy/summary
- В успешном ответе дополнительно: **`research_points`** (текущий баланс очков исследования), **`research_points_per_sol`** (пассив от столицы и лабораторий по `economy.json`).

## GET /api/effects/active
- **Метод:** `GET`
- **Успех 200:** активные эффекты игрока (из `player_effects`) для UI.
  ```json
  {
    "ok": true,
    "current_tick": 0,
    "effects": [
      {
        "id": 1,
        "effect_type": "research_speed_boost",
        "remaining_ticks": 4,
        "payload": { "time_multiplier": 0.85 }
      }
    ]
  }
  ```
- **Ошибки:** `401` → `{ "error": "not_authenticated" }`

---

## Дополнительно

### GET /api/health
- **Успех 200:**
  ```json
  { "status": "ok", "app": "GuardStar" }
  ```

### GET /api/ready
- **Успех 200:**
  ```json
  { "status": "ready" }
  ```
- **Ошибка 503:**
  ```json
  { "status": "not_ready", "error": "db_unavailable" }
  ```
