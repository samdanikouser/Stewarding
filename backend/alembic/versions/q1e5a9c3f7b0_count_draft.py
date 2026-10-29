"""count drafts saved while a person is counting

Revision ID: q1e5a9c3f7b0
Revises: p0d4f8b2e6a9
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "q1e5a9c3f7b0"
down_revision: Union[str, Sequence[str], None] = "p0d4f8b2e6a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "count_draft",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=False, index=True),
        sa.Column("location_id", sa.Integer(), sa.ForeignKey("location.id"), nullable=False),
        sa.Column("entries", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("user_id", "location_id", name="uq_count_draft_user_location"),
    )


def downgrade() -> None:
    op.drop_table("count_draft")
