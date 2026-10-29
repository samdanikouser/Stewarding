"""live face challenge and the snapshot taken at check-in and check-out

Revision ID: a3b9d5f1c7e4
Revises: f2a8c4e6b0d3
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a3b9d5f1c7e4"
down_revision: Union[str, Sequence[str], None] = "f2a8c4e6b0d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "face_challenge",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("employee_id", sa.Integer, sa.ForeignKey("employee.id"), nullable=False),
        sa.Column("token", sa.String(64), nullable=False, unique=True),
        sa.Column("action", sa.String(3), nullable=False),
        sa.Column("steps", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("used_at", sa.DateTime),
    )
    op.create_index("ix_face_challenge_employee_id", "face_challenge", ["employee_id"])
    op.create_index("ix_face_challenge_created_at", "face_challenge", ["created_at"])
    with op.batch_alter_table("attendance_record") as batch:
        batch.add_column(sa.Column("check_in_snapshot", sa.String(60)))
        batch.add_column(sa.Column("check_out_snapshot", sa.String(60)))


def downgrade() -> None:
    with op.batch_alter_table("attendance_record") as batch:
        batch.drop_column("check_out_snapshot")
        batch.drop_column("check_in_snapshot")
    op.drop_index("ix_face_challenge_created_at", "face_challenge")
    op.drop_index("ix_face_challenge_employee_id", "face_challenge")
    op.drop_table("face_challenge")
