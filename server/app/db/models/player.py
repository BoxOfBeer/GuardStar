from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


class Player(Base):
    __tablename__ = "players"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    display_name: Mapped[str] = mapped_column(String(64), nullable=False)
    access_code_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    # ID расы из balance pack (server/data/balance/races.json)
    race_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    research_points: Mapped[float] = mapped_column(
        Numeric(16, 6), nullable=False, default=0
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Включить запись API-действий (POST/PUT/PATCH/DELETE) в feedback_playtest_api_logs
    feedback_audited: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True
    )
