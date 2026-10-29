"""alternate-week roster assignments

Revision ID: c2e4a6b8d0f1
Revises: b9d1f3a5c7e2
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c2e4a6b8d0f1"
down_revision: Union[str, Sequence[str], None] = "b9d1f3a5c7e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("shift_assignment") as batch:
        batch.add_column(sa.Column("cycle_weeks", sa.Integer, nullable=False, server_default="1"))
        batch.add_column(sa.Column("cycle_week", sa.Integer, nullable=False, server_default="0"))


def downgrade() -> None:
    with op.batch_alter_table("shift_assignment") as batch:
        batch.drop_column("cycle_week")
        batch.drop_column("cycle_weeks")
