"""when a frozen lot was thawed and by whom

Revision ID: c5d1f7b3e9a6
Revises: b4c0e6a2d8f5
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c5d1f7b3e9a6"
down_revision: Union[str, Sequence[str], None] = "b4c0e6a2d8f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("lot") as batch:
        batch.add_column(sa.Column("thawed_at", sa.DateTime))
        batch.add_column(sa.Column("thawed_by", sa.Integer, sa.ForeignKey("user.id", name="fk_lot_thawed_by_user")))


def downgrade() -> None:
    with op.batch_alter_table("lot") as batch:
        batch.drop_column("thawed_by")
        batch.drop_column("thawed_at")
