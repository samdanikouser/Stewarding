"""lessons can be made into a video from slides

Revision ID: m7a1c5e9b3d6
Revises: l6f0b4d8a2e5
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "m7a1c5e9b3d6"
down_revision: Union[str, Sequence[str], None] = "l6f0b4d8a2e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("training_lesson") as batch:
        batch.add_column(sa.Column("slides", sa.JSON()))
        batch.add_column(sa.Column("video_status", sa.String(10)))
        batch.add_column(sa.Column("video_error", sa.String(300)))


def downgrade() -> None:
    with op.batch_alter_table("training_lesson") as batch:
        batch.drop_column("video_error")
        batch.drop_column("video_status")
        batch.drop_column("slides")
