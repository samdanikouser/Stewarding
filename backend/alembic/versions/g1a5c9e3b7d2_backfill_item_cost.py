"""set each item's reference cost to its latest priced purchase

Revision ID: g1a5c9e3b7d2
Revises: e4a6c8d0f2b3
"""
from decimal import ROUND_HALF_UP, Decimal
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "g1a5c9e3b7d2"
down_revision: Union[str, Sequence[str], None] = "e4a6c8d0f2b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT l.item_id, l.line_total, l.qty FROM receipt_line l JOIN receipt r ON r.id = l.receipt_id "
        "WHERE r.status = 'posted' AND r.doc_type = 'receipt' AND l.line_total > 0 AND l.qty > 0 "
        "ORDER BY COALESCE(r.invoice_date, r.received_at), r.id"))
    latest = {item_id: (Decimal(str(total)) / qty).quantize(Decimal("0.01"), ROUND_HALF_UP) for item_id, total, qty in rows}
    for item_id, cost in latest.items():
        bind.execute(sa.text("UPDATE inventory_item SET unit_cost = :c WHERE id = :i"), {"c": cost, "i": item_id})


def downgrade() -> None:
    pass  # the earlier reference costs are not kept
