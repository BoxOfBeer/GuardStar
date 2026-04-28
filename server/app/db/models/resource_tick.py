from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


class ResourceTick(Base):
    __tablename__ = "resource_ticks"

    planet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("planets.id", ondelete="CASCADE"), primary_key=True
    )
    last_collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

