from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


class PlayerEffect(Base):
    """Временные / одноразовые эффекты игрока (бусты исследований, кэш чертежей и т.п.)."""

    __tablename__ = "player_effects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("players.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    effect_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unknown"
    )
    source_ref: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_tick: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, index=True
    )
    expires_tick: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    used_at_tick: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
