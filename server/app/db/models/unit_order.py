from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


class UnitOrder(Base):
    __tablename__ = "unit_orders"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    unit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("units.id", ondelete="CASCADE"), nullable=False, index=True
    )
    order_type: Mapped[str] = mapped_column(String(32), nullable=False, default="move")

    target_x: Mapped[int] = mapped_column(Integer, nullable=False)
    target_y: Mapped[int] = mapped_column(Integer, nullable=False)
    target_z: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    start_tick: Mapped[int] = mapped_column(Integer, nullable=False)
    finish_tick: Mapped[int] = mapped_column(Integer, nullable=False)
