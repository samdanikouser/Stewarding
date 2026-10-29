"""days a location is closed, when its tasks and checks are not expected

Revision ID: t4b8d2f6a0c3
Revises: s3a7c1e5b9d2
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "t4b8d2f6a0c3"
down_revision: Union[str, Sequence[str], None] = "s3a7c1e5b9d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "closed_day",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("location_id", sa.Integer(), sa.ForeignKey("location.id"), index=True),
        sa.Column("start_date", sa.Date(), nullable=False, index=True),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("reason", sa.String(200), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("closed_day")
