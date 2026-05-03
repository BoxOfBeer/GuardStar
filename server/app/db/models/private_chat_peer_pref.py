from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


class PrivateChatPeerPref(Base):
    """Настройки оператора viewer относительно личной переписки с конкретным peer (двусторонняя модель по строкам)."""

    __tablename__ = "private_chat_peer_prefs"
    __table_args__ = (
        UniqueConstraint("viewer_player_id", "peer_player_id", name="uq_private_chat_peer_prefs_pair"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    viewer_player_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("players.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    peer_player_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("players.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Первое «прохождение» диалога (модалка про прочтение) выполнено
    welcomed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Сообщать ли собеседнику, когда я прочитываю его сообщения (read receipt)
    send_read_receipts: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Входящие от peer до этого id включительно не считаются непрочитанными для viewer
    last_read_incoming_id: Mapped[int] = mapped_column(BigInteger(), nullable=False, default=0)
    # Локальное скрытие диалога в списке (удалить чат) до нового сообщения собеседнику ко мне
    hidden_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
