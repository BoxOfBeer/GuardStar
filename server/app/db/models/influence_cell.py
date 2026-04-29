from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


class InfluenceCell(Base):
    __tablename__ = "influence_cells"
    __table_args__ = (UniqueConstraint("player_id", "x", "y", "z", name="uq_influence_cells_player_xyz"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("players.id", ondelete="CASCADE"), nullable=False, index=True
    )
    x: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    y: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    z: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)
    control_value: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    updated_tick: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

