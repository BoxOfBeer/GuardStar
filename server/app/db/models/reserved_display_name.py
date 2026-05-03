from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


class ReservedDisplayName(Base):
    """Каждый когда-либо занятый нормализованный операторский псевдоним блокируется навсегда."""

    __tablename__ = "reserved_display_names"

    id: Mapped[int] = mapped_column(BigInteger(), primary_key=True, autoincrement=True)
    name_norm: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    display_snapshot: Mapped[str] = mapped_column(String(64), nullable=False)
    player_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("players.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
