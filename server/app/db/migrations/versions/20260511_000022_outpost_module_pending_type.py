"""outpost_modules: pending upgrade target"""

from alembic import op
from sqlalchemy import inspect

import sqlalchemy as sa


revision = "20260511_000022"
down_revision = "20260510_000021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = inspect(conn)
    cols = {c["name"] for c in insp.get_columns("outpost_modules")}
    if "pending_module_type" not in cols:
        op.add_column(
            "outpost_modules",
            sa.Column("pending_module_type", sa.String(length=64), nullable=True),
        )


def downgrade() -> None:
    conn = op.get_bind()
    insp = inspect(conn)
    cols = {c["name"] for c in insp.get_columns("outpost_modules")}
    if "pending_module_type" in cols:
        op.drop_column("outpost_modules", "pending_module_type")
