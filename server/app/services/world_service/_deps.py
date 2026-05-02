from __future__ import annotations

import hashlib
import json
import random
import uuid
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.orm import Session

from app.fleet_defaults import fleet_display_name_for_index
from app.game_rules import (
    calc_fuel_cost,
    calc_planet_production,
    calc_travel_plan,
    calc_upkeep,
)
from app.db.models.event import Event
from app.db.models.explored_sector import ExploredSector
from app.db.models.influence_cell import InfluenceCell
from app.db.models.building import Building
from app.db.models.fleet import Fleet
from app.db.models.fleet_ship import FleetShip
from app.db.models.outpost import Outpost
from app.db.models.outpost_module import OutpostModule
from app.db.models.fleet_order import FleetOrder
from app.db.models.game_clock import GameClock
from app.db.models.world_state import WorldState
from app.db.models.planet import Planet
from app.db.models.resource import Resource
from app.db.models.resource_tick import ResourceTick
from app.db.models.unit import Unit
from app.db.models.unit_order import UnitOrder
from app.db.models.player import Player
from app.db.models.player_tech import PlayerTech
from app.services.player_research_effects import (
    EFFECT_ANOMALY_DATA,
    EFFECT_RESEARCH_FRAGMENTS,
    EFFECT_RUIN_ARCHIVES,
    count_field_data,
)
from app.services.discovery_service import try_resolve_ruins_anomaly_for_sector
from app.services.outpost_service import OutpostService
from app.services.player_research_effects import cleanup_expired_player_effects
from app.services.supply_service import SupplyService
