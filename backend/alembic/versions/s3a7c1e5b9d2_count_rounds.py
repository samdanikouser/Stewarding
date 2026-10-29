"""count rounds: a stock count over every location, checked as one pool

Revision ID: s3a7c1e5b9d2
Revises: r2f6b0d4a8c1
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "s3a7c1e5b9d2"
down_revision: Union[str, Sequence[str], None] = "r2f6b0d4a8c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "count_round",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, index=True),
        sa.Column("home_location_id", sa.Integer(), sa.ForeignKey("location.id")),
        sa.Column("baseline", sa.Boolean(), nullable=False),
        sa.Column("deadline", sa.Date()),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("posted_by", sa.Integer(), sa.ForeignKey("user.id")),
        sa.Column("posted_at", sa.DateTime()),
        sa.Column("note", sa.Text()),
    )
    op.create_table(
        "round_count",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("round_id", sa.Integer(), sa.ForeignKey("count_round.id"), nullable=False, index=True),
        sa.Column("location_id", sa.Integer(), sa.ForeignKey("location.id"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("user.id")),
        sa.Column("updated_at", sa.DateTime()),
        sa.Column("done_at", sa.DateTime()),
        sa.UniqueConstraint("round_id", "location_id", name="uq_round_count_location"),
    )
    op.create_table(
        "round_count_line",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("round_count_id", sa.Integer(), sa.ForeignKey("round_count.id"), nullable=False, index=True),
        sa.Column("item_id", sa.Integer(), sa.ForeignKey("inventory_item.id"), nullable=False, index=True),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.UniqueConstraint("round_count_id", "item_id", name="uq_round_count_line_item"),
    )
    op.create_table(
        "round_review",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("round_id", sa.Integer(), sa.ForeignKey("count_round.id"), nullable=False, index=True),
        sa.Column("item_id", sa.Integer(), sa.ForeignKey("inventory_item.id"), nullable=False),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("decided_by", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("decided_at", sa.DateTime(), nullable=False),
        sa.Column("note", sa.Text()),
        sa.UniqueConstraint("round_id", "item_id", name="uq_round_review_item"),
    )


def downgrade() -> None:
    for table in ("round_review", "round_count_line", "round_count", "count_round"):
        op.drop_table(table)
