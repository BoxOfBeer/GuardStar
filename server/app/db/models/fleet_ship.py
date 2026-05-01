from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


class FleetShip(Base):
    """Состав флота (несколько типов кораблей в одной стопке). Legacy: таблица fleets.unit_type/qty."""

    __tablename__ = "fleet_ships"

    fleet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("fleets.id", ondelete="CASCADE"),
        primary_key=True,
    )
    unit_type: Mapped[str] = mapped_column(String(32), primary_key=True)
    qty: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
