from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


class Resource(Base):
    __tablename__ = "resources"

    planet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("planets.id", ondelete="CASCADE"),
        primary_key=True,
    )
    metal: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    crystal: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    energy: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fuel: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    food: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    water: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
