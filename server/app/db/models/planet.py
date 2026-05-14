from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


class Planet(Base):
    __tablename__ = "planets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    owner_player_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("players.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    pos_x: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    pos_y: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    population: Mapped[int] = mapped_column(Integer, nullable=False, default=800)
    max_population: Mapped[int] = mapped_column(Integer, nullable=False, default=5000)
    planet_class: Mapped[str] = mapped_column(
        String(32), nullable=False, default="earthlike", index=True
    )
    build_slots_total: Mapped[int] = mapped_column(Integer, nullable=False, default=55)
    supplier_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_capital: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True
    )
    is_colonized: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, index=True
    )
    conquest_penalty_until_tick: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
