"""keep invoice prices, discounts and totals, and item prices, to a thousandth

Revision ID: j4d8f2b6e0c3
Revises: i3c7e1a5d9b2
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "j4d8f2b6e0c3"
down_revision: Union[str, Sequence[str], None] = "i3c7e1a5d9b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (table, column, digits); every value already stored keeps its amount, it simply gains a third place
COLUMNS = (
    ("receipt", "subtotal", 12), ("receipt", "line_discount_total", 12), ("receipt", "discount_value", 12),
    ("receipt", "discount_amount", 12), ("receipt", "total", 12),
    ("receipt_line", "unit_cost", 10), ("receipt_line", "discount_value", 12), ("receipt_line", "discount_amount", 12),
    ("receipt_line", "line_total", 12),
    ("inventory_item", "unit_cost", 10),
)


def _change(places_from: int, places_to: int) -> None:
    for table in dict.fromkeys(t for t, _, _ in COLUMNS):
        with op.batch_alter_table(table) as batch:
            for t, column, digits in COLUMNS:
                if t == table:
                    batch.alter_column(column, existing_type=sa.Numeric(digits, places_from), type_=sa.Numeric(digits, places_to))


def upgrade() -> None:
    _change(2, 3)


def downgrade() -> None:
    _change(3, 2)
