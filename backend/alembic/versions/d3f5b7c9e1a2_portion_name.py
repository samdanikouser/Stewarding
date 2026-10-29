"""managed list of portion names

Revision ID: d3f5b7c9e1a2
Revises: c2e4a6b8d0f1
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d3f5b7c9e1a2"
down_revision: Union[str, Sequence[str], None] = "c2e4a6b8d0f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "portion_name",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(120), nullable=False, unique=True),
        sa.Column("food_item_id", sa.Integer, sa.ForeignKey("food_item.id")),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
    )
    op.create_index("ix_portion_name_food_item_id", "portion_name", ["food_item_id"])


def downgrade() -> None:
    op.drop_index("ix_portion_name_food_item_id", table_name="portion_name")
    op.drop_table("portion_name")
