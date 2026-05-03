from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


class WorldState(Base):
    __tablename__ = "world_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    current_tick: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )

    auto_tick_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    auto_tick_interval_seconds: Mapped[float] = mapped_column(
        Float, nullable=False, default=10.0
    )

    #: Минимум |dx|+|dy| до любой существующей планеты при создании старта нового игрока.
    player_spawn_min_manhattan: Mapped[int] = mapped_column(
        Integer, nullable=False, default=25
    )

    #: Тест/админ: не создавать новые флоты (игроки, NPC-транзит, корсары) — см. API dev.
    test_block_new_fleets: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    #: Админка: запрет создания флота игроком с планеты (без «ядерного» test_block).
    admin_block_player_fleet_create: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    #: Админка: не спавнить транзитные NPC-конвои.
    admin_block_npc_transit: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    #: Админка: не ставить корсарские шахты в дикой зоне.
    admin_block_bandit_mines: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    #: Админка: не ставить корсарские форпосты.
    admin_block_bandit_outposts: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    #: Админка: патруль-респавн, ударные звена, MVP-патруль (не первый патруль у нового форпоста).
    admin_block_bandit_fleets: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    #: 0 = дефолт сервера (см. DEFAULT_MAX_FLEET_UNITS); иначе макс. кораблей в одном флоте.
    admin_max_fleet_units: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: JSON: {"time": {"1":1.0,"2":2.0}, "rp": {"1":1.0,"2":1.5}} — множители по tier теха.
    admin_research_overrides_json: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    #: JSON-фрагмент той же структуры, что `economy.json` (вложенные ключи), поверх файла.
    admin_economy_overrides_json: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
