"""reserved_display_names: уникальные операторские имена + исторические блокировки

Revision ID: 20260504_000020
Revises: 20260503_000019
Create Date: 2026-05-04

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision = "20260504_000020"
down_revision = "20260503_000019"
branch_labels = None
depends_on = None


def _prep_display_name(raw: str) -> str:
    return " ".join((raw or "").strip().split())[:64]


def _name_norm(prepared: str) -> str:
    return prepared.casefold()


def upgrade() -> None:
    conn = op.get_bind()
    insp = inspect(conn)
    if "reserved_display_names" not in insp.get_table_names():
        op.create_table(
            "reserved_display_names",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("name_norm", sa.String(length=64), nullable=False),
            sa.Column("display_snapshot", sa.String(length=64), nullable=False),
            sa.Column("player_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["player_id"],
                ["players.id"],
                name="reserved_display_names_player_id_fkey",
                ondelete="SET NULL",
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_reserved_display_names_name_norm",
            "reserved_display_names",
            ["name_norm"],
            unique=True,
        )
        op.create_index(
            "ix_reserved_display_names_player_id",
            "reserved_display_names",
            ["player_id"],
            unique=False,
        )

    rows = conn.execute(sa.text('SELECT id, display_name FROM players')).fetchall()
    seen: set[str] = set()
    for row in rows:
        pid, dn = row[0], str(row[1] or "")
        prepared = _prep_display_name(dn)
        nn = _name_norm(prepared)
        if not nn:
            continue
        if nn in seen:
            continue
        seen.add(nn)
        conn.execute(
            sa.text(
                """
                INSERT INTO reserved_display_names
                    (name_norm, display_snapshot, player_id, created_at)
                VALUES (:nn, :ds, :pid, CURRENT_TIMESTAMP)
                ON CONFLICT (name_norm) DO NOTHING
                """
            ),
            {"nn": nn, "ds": prepared[:64], "pid": pid},
        )


def downgrade() -> None:
    conn = op.get_bind()
    insp = inspect(conn)
    if "reserved_display_names" not in insp.get_table_names():
        return
    op.drop_index(
        "ix_reserved_display_names_player_id", table_name="reserved_display_names"
    )
    op.drop_index("ix_reserved_display_names_name_norm", table_name="reserved_display_names")
    op.drop_table("reserved_display_names")
