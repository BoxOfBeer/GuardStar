from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


class OutpostModule(Base):
    __tablename__ = "outpost_modules"
    __table_args__ = (
        UniqueConstraint("outpost_id", "slot_idx", name="uq_outpost_modules_slot"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    outpost_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("outposts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    module_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    pending_module_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    level: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    slot_idx: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="active", index=True
    )
    started_at_tick: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    finish_tick: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
