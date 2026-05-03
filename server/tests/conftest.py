import os

import pytest
from sqlalchemy import create_engine

from app.db.models import Base
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
from app.db.models.private_chat_peer_pref import PrivateChatPeerPref  # noqa: F401
from app.db.models.player_block import PlayerBlock  # noqa: F401
from app.db.models.player_effect import PlayerEffect  # noqa: F401
from app.db.models.player_tech import PlayerTech  # noqa: F401
from app.db.models.resource import Resource  # noqa: F401
from app.db.models.resource_tick import ResourceTick  # noqa: F401
from app.db.models.reserved_display_name import ReservedDisplayName  # noqa: F401
from app.db.models.unit import Unit  # noqa: F401
from app.db.models.unit_order import UnitOrder  # noqa: F401
from app.db.models.world_state import WorldState  # noqa: F401


@pytest.fixture(scope="session")
def database_url() -> str:
    url = (os.environ.get("TEST_DATABASE_URL") or "").strip()
    if not url:
        pytest.skip(
            "Задайте TEST_DATABASE_URL (отдельная БД для интеграционных тестов с `client`). "
            "Тесты создают игроков с префиксом имени gs_py_ и удаляют их сами; без TRUNCATE."
        )
    return url


@pytest.fixture(scope="session")
def _test_engine(database_url: str):
    engine = create_engine(database_url, future=True)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def client(monkeypatch, database_url: str, _test_engine):
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("SERVER_SALT", "test-salt")

    from app import create_app

    app = create_app()
    app.config.update(TESTING=True)

    return app.test_client()
