from __future__ import annotations

import hashlib
import secrets
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.player import Player


class AuthService:
    def __init__(self, server_salt: str) -> None:
        if not server_salt:
            raise ValueError("SERVER_SALT must be set")
        self._server_salt = server_salt

    def generate_access_code(self) -> str:
        # 32 символа: hex(16 bytes) -> 32 chars
        return secrets.token_hex(16)

    def hash_access_code(self, access_code: str) -> str:
        raw = (access_code + self._server_salt).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def register_player(self, s: Session, *, display_name: str) -> tuple[Player, str]:
        # Пытаемся избегать коллизий на практике (не должны случаться).
        for _ in range(5):
            access_code = self.generate_access_code()
            access_code_hash = self.hash_access_code(access_code)

            existing = s.execute(select(Player.id).where(Player.access_code_hash == access_code_hash)).first()
            if existing:
                continue

            player = Player(display_name=display_name, access_code_hash=access_code_hash)
            s.add(player)
            s.flush()
            return player, access_code

        raise RuntimeError("Failed to generate unique access code")

    def authenticate_by_code(self, s: Session, *, access_code: str) -> Player | None:
        access_code_hash = self.hash_access_code(access_code)
        player = s.execute(select(Player).where(Player.access_code_hash == access_code_hash)).scalar_one_or_none()
        if not player:
            return None

        player.last_login_at = datetime.utcnow()
        s.flush()
        return player

