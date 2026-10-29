"""the currency shown with amounts

Revision ID: o9c3e7a1d5f8
Revises: n8b2d6f0c4e7
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "o9c3e7a1d5f8"
down_revision: Union[str, Sequence[str], None] = "n8b2d6f0c4e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("organization") as batch:
        batch.add_column(sa.Column("currency", sa.String(8)))


def downgrade() -> None:
    with op.batch_alter_table("organization") as batch:
        batch.drop_column("currency")
