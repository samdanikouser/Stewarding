"""fill an item's blank starting cost from its latest priced invoice

Revision ID: n8b2d6f0c4e7
Revises: m7a1c5e9b3d6
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "n8b2d6f0c4e7"
down_revision: Union[str, Sequence[str], None] = "m7a1c5e9b3d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    db = op.get_bind()
    blanks = db.execute(sa.text("SELECT id FROM inventory_item WHERE unit_cost IS NULL")).scalars().all()
    for item_id in blanks:
        latest = db.execute(sa.text(
            "SELECT l.line_total, l.qty FROM receipt_line l JOIN receipt r ON r.id = l.receipt_id "
            "WHERE l.item_id = :i AND r.status = 'posted' AND r.doc_type = 'receipt' AND l.line_total IS NOT NULL AND l.qty > 0 "
            "ORDER BY COALESCE(r.invoice_date, r.received_at) DESC, r.id DESC LIMIT 1"), {"i": item_id}).first()
        if latest:
            db.execute(sa.text("UPDATE inventory_item SET unit_cost = :c WHERE id = :i"), {"c": round(latest[0] / latest[1], 3), "i": item_id})


def downgrade() -> None:
    pass  # the filled costs are ordinary data and stay
