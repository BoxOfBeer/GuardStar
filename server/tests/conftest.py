import os

import pytest
from sqlalchemy import create_engine

from app.db.models import Base
from app.db.models.fleet import Fleet  # noqa: F401
from app.db.models.game_clock import GameClock  # noqa: F401
from app.db.models.influence_cell import InfluenceCell  # noqa: F401
from app.db.models.outpost import Outpost  # noqa: F401
from app.db.models.outpost_module import OutpostModule  # noqa: F401
from app.db.models.planet import Planet  # noqa: F401
from app.db.models.player import Player  # noqa: F401
from app.db.models.resource import Resource  # noqa: F401
from app.db.models.resource_tick import ResourceTick  # noqa: F401
from app.db.models.unit import Unit  # noqa: F401
from app.db.models.unit_order import UnitOrder  # noqa: F401
from app.db.models.explored_sector import ExploredSector  # noqa: F401
from app.db.models.player_effect import PlayerEffect  # noqa: F401
from app.db.models.player_tech import PlayerTech  # noqa: F401
from app.db.models.world_state import WorldState  # noqa: F401
from app.db.models.event import Event  # noqa: F401
from app.db.models.fleet_ship import FleetShip  # noqa: F401


@pytest.fixture(scope="session")
def database_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL or DATABASE_URL to run DB tests (PostgreSQL).")
    return url


@pytest.fixture()
def db_schema(database_url: str):
    engine = create_engine(database_url, future=True)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture()
def client(monkeypatch, database_url: str, db_schema):
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("SERVER_SALT", "test-salt")

    from app import create_app

    app = create_app()
    app.config.update(TESTING=True)

    return app.test_client()

