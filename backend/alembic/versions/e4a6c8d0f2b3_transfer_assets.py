"""tracked assets named on a stock transfer line

Revision ID: e4a6c8d0f2b3
Revises: d3f5b7c9e1a2
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e4a6c8d0f2b3"
down_revision: Union[str, Sequence[str], None] = "d3f5b7c9e1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("inventory_transfer_line") as batch:
        batch.add_column(sa.Column("asset_ids", sa.JSON))


def downgrade() -> None:
    with op.batch_alter_table("inventory_transfer_line") as batch:
        batch.drop_column("asset_ids")
