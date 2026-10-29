"""the day the goods arrived, kept apart from the moment the document was entered

Revision ID: i3c7e1a5d9b2
Revises: h2b6d0f4c8a1
"""
from datetime import datetime
from typing import Sequence, Union
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from alembic import op

revision: str = "i3c7e1a5d9b2"
down_revision: Union[str, Sequence[str], None] = "h2b6d0f4c8a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("receipt") as batch:
        batch.add_column(sa.Column("received_on", sa.Date()))
    bind = op.get_bind()
    # every document so far counts as received the local day it was entered
    rows = bind.execute(sa.text("SELECT r.id, r.received_at, l.timezone FROM receipt r JOIN location l ON l.id = r.location_id")).all()
    for receipt_id, entered, tz in rows:
        if isinstance(entered, str):
            entered = datetime.fromisoformat(entered)
        day = entered.replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo(tz)).date()
        bind.execute(sa.text("UPDATE receipt SET received_on = :d WHERE id = :i"), {"d": day, "i": receipt_id})


def downgrade() -> None:
    with op.batch_alter_table("receipt") as batch:
        batch.drop_column("received_on")
