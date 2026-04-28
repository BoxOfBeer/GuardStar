from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


class GameClock(Base):
    __tablename__ = "game_clock"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    current_tick: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
