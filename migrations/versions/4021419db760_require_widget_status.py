"""Require a workflow status for widgets.

Revision ID: 4021419db760
Revises: 13ebb4e4e9ca
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4021419db760"
down_revision: str | None = "13ebb4e4e9ca"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute("UPDATE widget SET status = 'draft' WHERE status IS NULL")
    with op.batch_alter_table("widget") as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=sa.String(length=64),
            nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("widget") as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=sa.String(length=64),
            nullable=True,
        )
