"""QR scans of monitoring points and locations

Revision ID: b9d1f3a5c7e2
Revises: f8a4c0e6b2d9
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b9d1f3a5c7e2"
down_revision: Union[str, Sequence[str], None] = "f8a4c0e6b2d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "scan_event",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("user.id"), nullable=False),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("target_id", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_scan_event_lookup", "scan_event", ["user_id", "kind", "target_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_scan_event_lookup", table_name="scan_event")
    op.drop_table("scan_event")
