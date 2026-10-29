"""a Head Chef role that approves monitoring logs and corrective actions and sees nothing else

Revision ID: p0d4f8b2e6a9
Revises: o9c3e7a1d5f8
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "p0d4f8b2e6a9"
down_revision: Union[str, Sequence[str], None] = "o9c3e7a1d5f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NAME, LABEL = "head_chef", "Head Chef"
# supervisor tier so they see every task at their kitchens; no inventory, employees, attendance, roster, reports or settings
PERMISSIONS = ("dashboard.view", "checklist.view", "checklist.verify", "temp.view", "temp.review", "notification.view", "training.view")


def upgrade() -> None:
    db = op.get_bind()
    taken = db.execute(sa.text("SELECT id FROM role WHERE name = :n OR lower(label) = lower(:l)"), {"n": NAME, "l": LABEL}).first()
    if taken:
        return  # someone already made a role by this name; leave theirs alone
    db.execute(sa.text("INSERT INTO role (name, label, tier, builtin) VALUES (:n, :l, 'supervisor', :b)"), {"n": NAME, "l": LABEL, "b": False})
    role_id = db.execute(sa.text("SELECT id FROM role WHERE name = :n"), {"n": NAME}).scalar_one()
    for permission in PERMISSIONS:
        db.execute(sa.text("INSERT INTO role_permission (role_id, permission) VALUES (:r, :p)"), {"r": role_id, "p": permission})


def downgrade() -> None:
    pass  # the role may by now have people in it
