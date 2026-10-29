"""the suppliers an item is also bought from

Revision ID: r2f6b0d4a8c1
Revises: q1e5a9c3f7b0
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "r2f6b0d4a8c1"
down_revision: Union[str, Sequence[str], None] = "q1e5a9c3f7b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "item_supplier",
        sa.Column("item_id", sa.Integer(), sa.ForeignKey("inventory_item.id"), primary_key=True),
        sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("supplier.id"), primary_key=True, index=True),
    )
    # suppliers already seen on posted invoices become suppliers of those items
    op.execute(
        "INSERT INTO item_supplier (item_id, supplier_id) "
        "SELECT DISTINCT l.item_id, r.supplier_id FROM receipt_line l JOIN receipt r ON r.id = l.receipt_id "
        "JOIN inventory_item i ON i.id = l.item_id "
        "WHERE r.status = 'posted' AND r.doc_type = 'receipt' AND (i.supplier_id IS NULL OR i.supplier_id <> r.supplier_id)")


def downgrade() -> None:
    op.drop_table("item_supplier")
