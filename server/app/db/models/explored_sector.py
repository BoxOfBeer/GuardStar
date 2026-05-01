from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


class ExploredSector(Base):
    __tablename__ = "explored_sectors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("players.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    x: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    y: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    z: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)

    first_seen_tick: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_seen_tick: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, index=True
    )

    discovery_done: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    discovery_seen_tick: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
