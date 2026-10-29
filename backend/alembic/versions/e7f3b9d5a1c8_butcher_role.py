"""give supervisors the lot permissions and add the Butcher role

Revision ID: e7f3b9d5a1c8
Revises: d6e2a8c4f0b7
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e7f3b9d5a1c8"
down_revision: Union[str, Sequence[str], None] = "d6e2a8c4f0b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SUPERVISOR_LOT_PERMISSIONS = ["lot.view", "lot.receive"]
BUTCHER_PERMISSIONS = [
    "dashboard.view", "attendance.self", "checklist.view", "checklist.complete",
    "temp.view", "temp.record", "notification.view", "lot.view", "lot.split",
]

role = sa.table("role", sa.column("id", sa.Integer), sa.column("name", sa.String), sa.column("label", sa.String),
                sa.column("tier", sa.String), sa.column("builtin", sa.Boolean))
role_permission = sa.table("role_permission", sa.column("role_id", sa.Integer), sa.column("permission", sa.String))
app_user = sa.table("user", sa.column("role_id", sa.Integer))


def _role_id(name: str) -> int | None:
    return op.get_bind().scalar(sa.select(role.c.id).where(role.c.name == name))


def _grant(role_id: int, permissions: list[str]) -> None:
    bind = op.get_bind()
    have = set(bind.scalars(sa.select(role_permission.c.permission).where(role_permission.c.role_id == role_id)))
    missing = [p for p in permissions if p not in have]
    if missing:
        op.bulk_insert(role_permission, [{"role_id": role_id, "permission": p} for p in missing])


def upgrade() -> None:
    supervisor = _role_id("supervisor")
    if supervisor:
        _grant(supervisor, SUPERVISOR_LOT_PERMISSIONS)
    if not _role_id("butcher"):
        op.bulk_insert(role, [{"name": "butcher", "label": "Butcher", "tier": "steward", "builtin": False}])
    _grant(_role_id("butcher"), BUTCHER_PERMISSIONS)


def downgrade() -> None:
    butcher = _role_id("butcher")
    if not butcher:
        return
    bind = op.get_bind()
    if bind.scalar(sa.select(sa.func.count()).select_from(app_user).where(app_user.c.role_id == butcher)):
        return
    bind.execute(role_permission.delete().where(role_permission.c.role_id == butcher))
    bind.execute(role.delete().where(role.c.id == butcher))
