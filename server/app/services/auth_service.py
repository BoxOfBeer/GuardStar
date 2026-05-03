from __future__ import annotations

import hashlib
import secrets
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models.player import Player
from app.db.models.reserved_display_name import ReservedDisplayName


class DisplayNameInvalid(Exception):
    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


OPERATOR_DISPLAY_NAME_MIN = 3
OPERATOR_DISPLAY_NAME_MAX = 64


def prepare_operator_display_name(raw: str | None) -> str:
    return " ".join((raw or "").strip().split())[:OPERATOR_DISPLAY_NAME_MAX]


def normalized_operator_name(prepared: str) -> str:
    return prepared.casefold()


def validate_prepared_operator_name(prepared: str) -> str | None:
    if not prepared:
        return "empty"
    if len(prepared) < OPERATOR_DISPLAY_NAME_MIN:
        return "too_short"
    if len(prepared) > OPERATOR_DISPLAY_NAME_MAX:
        return "too_long"
    return None


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

    def register_player(
        self, s: Session, *, display_name: str, race_id: str = "human"
    ) -> tuple[Player, str]:
        prepared = prepare_operator_display_name(display_name)
        err = validate_prepared_operator_name(prepared)
        if err:
            raise DisplayNameInvalid(err)
        nn = normalized_operator_name(prepared)
        taken = s.execute(
            select(ReservedDisplayName.id).where(ReservedDisplayName.name_norm == nn)
        ).first()
        if taken:
            raise DisplayNameInvalid("taken")

        for _ in range(5):
            access_code = self.generate_access_code()
            access_code_hash = self.hash_access_code(access_code)

            existing = s.execute(
                select(Player.id).where(Player.access_code_hash == access_code_hash)
            ).first()
            if existing:
                continue

            player = Player(
                display_name=prepared,
                access_code_hash=access_code_hash,
                race_id=race_id,
            )
            s.add(player)
            s.flush()
            s.add(
                ReservedDisplayName(
                    name_norm=nn,
                    display_snapshot=prepared,
                    player_id=player.id,
                )
            )
            try:
                s.flush()
            except IntegrityError:
                raise DisplayNameInvalid("taken") from None
            return player, access_code

        raise RuntimeError("Failed to generate unique access code")

    def rename_player(self, s: Session, *, player: Player, new_display_name_raw: str) -> None:
        new_prepared = prepare_operator_display_name(new_display_name_raw)
        err = validate_prepared_operator_name(new_prepared)
        if err:
            raise DisplayNameInvalid(err)
        old_prep = prepare_operator_display_name(player.display_name)
        nn_new = normalized_operator_name(new_prepared)
        nn_old = normalized_operator_name(old_prep)

        if nn_new == nn_old:
            player.display_name = new_prepared
            s.flush()
            return

        row = s.execute(
            select(ReservedDisplayName).where(ReservedDisplayName.name_norm == nn_new)
        ).scalar_one_or_none()
        if row is not None and row.player_id != player.id:
            raise DisplayNameInvalid("taken")

        player.display_name = new_prepared
        s.flush()
        s.add(
            ReservedDisplayName(
                name_norm=nn_new,
                display_snapshot=new_prepared,
                player_id=player.id,
            )
        )
        try:
            s.flush()
        except IntegrityError:
            raise DisplayNameInvalid("taken") from None

    def authenticate_by_code(self, s: Session, *, access_code: str) -> Player | None:
        access_code_hash = self.hash_access_code(access_code)
        player = s.execute(
            select(Player).where(Player.access_code_hash == access_code_hash)
        ).scalar_one_or_none()
        if not player:
            return None
        if bool(getattr(player, "account_disabled", False)):
            return None

        player.last_login_at = datetime.utcnow()
        s.flush()
        return player
