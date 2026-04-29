from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


class Fleet(Base):
    __tablename__ = "fleets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_player_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("players.id", ondelete="CASCADE"), nullable=False, index=True
    )
    unit_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    qty: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    name: Mapped[str] = mapped_column(String(64), nullable=False, default="")

    pos_x: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    pos_y: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    pos_z: Mapped[int] = mapped_column(Integer, nullable=False, index=True, default=0)

    # Локальная энергия флота (не зависит от имперских ресурсов).
    energy: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    max_energy: Mapped[int] = mapped_column(Integer, nullable=False, default=100)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

