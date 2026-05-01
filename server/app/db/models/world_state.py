from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer
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
        Float, nullable=False, default=5.0
    )

    #: Минимум |dx|+|dy| до любой существующей планеты при создании старта нового игрока.
    player_spawn_min_manhattan: Mapped[int] = mapped_column(
        Integer, nullable=False, default=25
    )
