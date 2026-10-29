"""keep the estimated cost of a breakage report to a thousandth

Revision ID: k5e9a3c7f1d4
Revises: j4d8f2b6e0c3
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "k5e9a3c7f1d4"
down_revision: Union[str, Sequence[str], None] = "j4d8f2b6e0c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("breakage_incident") as batch:
        batch.alter_column("est_cost", existing_type=sa.Numeric(10, 2), type_=sa.Numeric(10, 3))


def downgrade() -> None:
    with op.batch_alter_table("breakage_incident") as batch:
        batch.alter_column("est_cost", existing_type=sa.Numeric(10, 3), type_=sa.Numeric(10, 2))
