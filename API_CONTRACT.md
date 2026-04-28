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
        "resources": { "metal": 500, "crystal": 250, "energy": 100 },
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
    "status": "moved",
    "target": { "x": 1, "y": 0, "z": 0 }
  }
  ```
- **Ошибки:**
  - `401` → `{ "error": "not_authenticated" }`
  - `400` → `{ "error": "invalid_coords" }`
  - `400` → `{ "ok": false, "error": "no_home_planet" }`
  - `400` → `{ "ok": false, "error": "z_not_supported_yet" }`
  - `400` → `{ "ok": false, "error": "target_not_adjacent" }`
  - `400` → `{ "ok": false, "error": "not_enough_scouts" }`

## GET /api/version
- **Метод:** `GET`
- **Request body:** отсутствует
- **Успех 200:**
  ```json
  {
    "app": "guardstar",
    "features": {
      "z_layers": true,
      "procgen": true,
      "move_scout": true,
      "resource_tick": true
    }
  }
  ```
- **Ошибки:** отсутствуют в текущей реализации.

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
