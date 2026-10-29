"""trim and loss recorded when a lot is cut into portions

Revision ID: f8a4c0e6b2d9
Revises: e7f3b9d5a1c8
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f8a4c0e6b2d9"
down_revision: Union[str, Sequence[str], None] = "e7f3b9d5a1c8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("lot") as batch:
        batch.add_column(sa.Column("waste_qty", sa.Numeric(10, 2)))


def downgrade() -> None:
    with op.batch_alter_table("lot") as batch:
        batch.drop_column("waste_qty")
