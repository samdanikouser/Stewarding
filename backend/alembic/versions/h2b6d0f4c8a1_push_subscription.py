"""browsers and phones that asked for push alerts

Revision ID: h2b6d0f4c8a1
Revises: g1a5c9e3b7d2
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "h2b6d0f4c8a1"
down_revision: Union[str, Sequence[str], None] = "g1a5c9e3b7d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "push_subscription",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=False, index=True),
        sa.Column("endpoint", sa.String(600), nullable=False, unique=True),
        sa.Column("p256dh", sa.String(200), nullable=False),
        sa.Column("auth", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("push_subscription")
