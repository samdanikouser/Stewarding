"""food traceability: lots, links, shelf-life rules and the lots a reading used

Revision ID: b4c0e6a2d8f5
Revises: a3b9d5f1c7e4
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b4c0e6a2d8f5"
down_revision: Union[str, Sequence[str], None] = "a3b9d5f1c7e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "food_item",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(120), nullable=False, unique=True),
        sa.Column("food_group", sa.String(20), nullable=False),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
    )
    op.create_table(
        "shelf_life_rule",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("food_group", sa.String(20), nullable=False),
        sa.Column("condition", sa.String(20), nullable=False),
        sa.Column("hours", sa.Integer, nullable=False),
        sa.Column("note", sa.String(300)),
        sa.UniqueConstraint("food_group", "condition", name="uq_shelf_life_rule"),
    )
    op.create_table(
        "lot",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("code", sa.String(48), nullable=False, unique=True),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("food_item_id", sa.Integer, sa.ForeignKey("food_item.id"), nullable=False),
        sa.Column("food_group", sa.String(20), nullable=False),
        sa.Column("condition", sa.String(20), nullable=False),
        sa.Column("supplier_id", sa.Integer, sa.ForeignKey("supplier.id")),
        sa.Column("supplier_lot", sa.String(60)),
        sa.Column("produced_on", sa.Date),
        sa.Column("expiry_on", sa.Date),
        sa.Column("use_by", sa.DateTime),
        sa.Column("temp_c", sa.Numeric(5, 1)),
        sa.Column("qty", sa.Numeric(10, 2)),
        sa.Column("unit", sa.String(20)),
        sa.Column("pack_count", sa.Integer),
        sa.Column("pack_description", sa.String(120)),
        sa.Column("tag_number", sa.String(60)),
        sa.Column("location_id", sa.Integer, sa.ForeignKey("location.id"), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("note", sa.Text),
        sa.Column("created_by", sa.Integer, sa.ForeignKey("user.id"), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    for column in ("food_item_id", "food_group", "use_by", "location_id", "status", "created_at"):
        op.create_index(f"ix_lot_{column}", "lot", [column])
    op.create_table(
        "lot_link",
        sa.Column("parent_id", sa.Integer, sa.ForeignKey("lot.id"), primary_key=True),
        sa.Column("child_id", sa.Integer, sa.ForeignKey("lot.id"), primary_key=True),
    )
    op.create_index("ix_lot_link_child_id", "lot_link", ["child_id"])
    op.create_table(
        "lot_event",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("lot_id", sa.Integer, sa.ForeignKey("lot.id"), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("detail", sa.String(300), nullable=False),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("user.id"), nullable=False),
        sa.Column("at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_lot_event_lot_id", "lot_event", ["lot_id"])
    op.create_table(
        "reading_lot",
        sa.Column("reading_id", sa.Integer, sa.ForeignKey("temperature_reading.id"), primary_key=True),
        sa.Column("lot_id", sa.Integer, sa.ForeignKey("lot.id"), primary_key=True),
    )
    op.create_index("ix_reading_lot_lot_id", "reading_lot", ["lot_id"])
    with op.batch_alter_table("equipment_schedule") as batch:
        batch.add_column(sa.Column("trace_lots", sa.Boolean, nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("equipment_schedule") as batch:
        batch.drop_column("trace_lots")
    op.drop_index("ix_reading_lot_lot_id", "reading_lot")
    op.drop_table("reading_lot")
    op.drop_index("ix_lot_event_lot_id", "lot_event")
    op.drop_table("lot_event")
    op.drop_index("ix_lot_link_child_id", "lot_link")
    op.drop_table("lot_link")
    for column in ("created_at", "status", "location_id", "use_by", "food_group", "food_item_id"):
        op.drop_index(f"ix_lot_{column}", "lot")
    op.drop_table("lot")
    op.drop_table("shelf_life_rule")
    op.drop_table("food_item")
