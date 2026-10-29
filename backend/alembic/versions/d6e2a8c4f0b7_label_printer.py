"""network label printers the server prints to

Revision ID: d6e2a8c4f0b7
Revises: c5d1f7b3e9a6
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d6e2a8c4f0b7"
down_revision: Union[str, Sequence[str], None] = "c5d1f7b3e9a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "label_printer",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(60), nullable=False, unique=True),
        sa.Column("host", sa.String(120), nullable=False),
        sa.Column("port", sa.Integer, nullable=False),
        sa.Column("dpi", sa.Integer, nullable=False),
        sa.Column("location_id", sa.Integer, sa.ForeignKey("location.id")),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_table("label_printer")
