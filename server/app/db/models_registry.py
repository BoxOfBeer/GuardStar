"""Импорт всех ORM-моделей — побочный эффект: регистрация в Base.metadata."""

from __future__ import annotations


def import_all_models() -> None:
    from app.db.models.admin_config import AdminConfig  # noqa: F401
    from app.db.models.building import Building  # noqa: F401
    from app.db.models.chat_message import ChatMessage  # noqa: F401
    from app.db.models.event import Event  # noqa: F401
    from app.db.models.explored_sector import ExploredSector  # noqa: F401
    from app.db.models.feedback_message import FeedbackMessage  # noqa: F401
    from app.db.models.feedback_playtest_api_log import FeedbackPlaytestApiLog  # noqa: F401
    from app.db.models.fleet import Fleet  # noqa: F401
    from app.db.models.fleet_order import FleetOrder  # noqa: F401
    from app.db.models.fleet_ship import FleetShip  # noqa: F401
    from app.db.models.game_clock import GameClock  # noqa: F401
    from app.db.models.influence_cell import InfluenceCell  # noqa: F401
    from app.db.models.outpost import Outpost  # noqa: F401
    from app.db.models.outpost_module import OutpostModule  # noqa: F401
    from app.db.models.planet import Planet  # noqa: F401
    from app.db.models.player import Player  # noqa: F401
    from app.db.models.player_block import PlayerBlock  # noqa: F401
    from app.db.models.player_effect import PlayerEffect  # noqa: F401
    from app.db.models.player_tech import PlayerTech  # noqa: F401
    from app.db.models.resource import Resource  # noqa: F401
    from app.db.models.private_chat_peer_pref import PrivateChatPeerPref  # noqa: F401
    from app.db.models.resource_tick import ResourceTick  # noqa: F401
    from app.db.models.reserved_display_name import ReservedDisplayName  # noqa: F401
    from app.db.models.unit import Unit  # noqa: F401
    from app.db.models.unit_order import UnitOrder  # noqa: F401
    from app.db.models.world_state import WorldState  # noqa: F401
