from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


class FleetOrder(Base):
    __tablename__ = "fleet_orders"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    fleet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("fleets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    owner_player_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("players.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    order_type: Mapped[str] = mapped_column(String(32), nullable=False, default="move")

    from_x: Mapped[int] = mapped_column(Integer, nullable=False)
    from_y: Mapped[int] = mapped_column(Integer, nullable=False)
    from_z: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    target_x: Mapped[int] = mapped_column(Integer, nullable=False)
    target_y: Mapped[int] = mapped_column(Integer, nullable=False)
    target_z: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    qty: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="queued", index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
    start_tick: Mapped[int] = mapped_column(Integer, nullable=False)
    finish_tick: Mapped[int] = mapped_column(Integer, nullable=False)

    # Если true — при прилёте на клетку с врагом бой сразу, без второго подтверждения.
    force_attack: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Для status=pending_combat: дедлайн реального времени для подтверждения / автоотказа.
    combat_prompt_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
