"""Константы домена мира (влияние, NPC, склад планеты, энергия флота)."""

from __future__ import annotations

import uuid

# Фиксированный «NPC» для вражеских засад в MVP (не логинится).
BANDIT_PLAYER_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
# Нейтральные транзитные конвои (не логинятся).
CIVILIAN_NPC_PLAYER_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
NPC_FLEET_PLAYER_IDS = frozenset({BANDIT_PLAYER_ID, CIVILIAN_NPC_PLAYER_ID})

# Территориальное влияние:
# - в гарант-радиусе сила источника постоянная;
# - далее каждую клетку делим влияние пополам.
INFLUENCE_WEIGHT_COLONY = 1.0
INFLUENCE_WEIGHT_BUILDING = 0.4
INFLUENCE_RADIUS_COLONY = 40
INFLUENCE_RADIUS_BUILDING = 14
INFLUENCE_BASE_RADIUS = 3
INFLUENCE_MIN_DOMINANT_SCORE = 0.1
INFLUENCE_CONTEST_RATIO = 0.68
INFLUENCE_CAPTURE_THRESHOLD = 1.0
INFLUENCE_NATURAL_DECAY_PER_TICK = 0.1
# MVP: control_value накапливается тиками и без ограничений быстро уходит в сотни/тысячи.
# Это не добавляет геймплейной информации (порог захвата уже 1.0), но ломает читаемость.
INFLUENCE_CONTROL_VALUE_CAP = 5.0
INFLUENCE_BUILDING_TYPES = {"outpost", "fortified_outpost", "command_post"}

# Склад планеты и производство за игровой сол (металл…вода).
PLANET_STORE_KEYS = ("metal", "crystal", "energy", "fuel", "food", "water")

# Локальная энергия флота: ёмкость (и реген в снабжении) масштабируются с тем же
# «энергетическим upkeep», что и стоимость прыжка за клетку — иначе крупный флот
# не проходит дальше 1–2 клеток при max=100.
FLEET_ENERGY_MAX_UPKEEP_MULT = 12
FLEET_ENERGY_MAX_ABS_CAP = 8000
FLEET_ENERGY_MAX_FLOOR = 100

# Максимум единиц в одном флоте (состав), если в world_state.admin_max_fleet_units = 0.
DEFAULT_MAX_FLEET_UNITS = 50
