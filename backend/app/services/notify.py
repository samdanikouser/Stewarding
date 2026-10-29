from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Employee, EmployeeLocation, Notification, Role, RolePermission, User
from ..permissions import MANAGER
from .push import queue


def recipients(db: Session, location_id: int | None, *roles: str) -> list[int]:
    """Active users whose role behaves like one of `roles` (a tier) at the location; managers are included when asked for."""
    base = (
        select(User.id)
        .join(Role, User.role_id == Role.id)
        .join(Employee, Employee.user_id == User.id)
        .where(User.active.is_(True), Employee.status == "active", Role.tier.in_(roles))
    )
    non_manager = [r for r in roles if r != MANAGER]
    ids: set[int] = set()
    if MANAGER in roles:
        ids |= set(db.scalars(base.where(Role.tier == MANAGER)))
    if non_manager and location_id is not None:
        q = base.join(EmployeeLocation, EmployeeLocation.employee_id == Employee.id).where(
            EmployeeLocation.location_id == location_id, Role.tier.in_(non_manager)
        )
        ids |= set(db.scalars(q))
    return sorted(ids)


def holders_of(db: Session, permission: str, location_id: int | None = None) -> list[int]:
    """Active users whose role grants `permission`: managers everywhere, other roles at the location."""
    base = (
        select(User.id)
        .join(Role, User.role_id == Role.id)
        .join(RolePermission, RolePermission.role_id == Role.id)
        .join(Employee, Employee.user_id == User.id)
        .where(User.active.is_(True), Employee.status == "active", RolePermission.permission == permission)
    )
    ids = set(db.scalars(base.where(Role.tier == MANAGER)))
    if location_id is not None:
        ids |= set(db.scalars(base.join(EmployeeLocation, EmployeeLocation.employee_id == Employee.id).where(
            EmployeeLocation.location_id == location_id, Role.tier != MANAGER)))
    return sorted(ids)


def notify(db: Session, user_ids, kind: str, title: str, *, key: str, body: str | None = None,
           priority: str = "normal", location_id: int | None = None, link: str | None = None,
           due_at=None, requires_ack: bool = False) -> int:
    """One notification per recipient and `key`; returns how many were newly created."""
    created = 0
    for uid in set(user_ids):
        if db.scalar(select(Notification.id).where(Notification.user_id == uid, Notification.dedupe_key == key)):
            continue
        db.add(Notification(user_id=uid, kind=kind, title=title, body=body, priority=priority,
                            location_id=location_id, link=link, dedupe_key=key, due_at=due_at,
                            requires_ack=requires_ack))
        db.flush()
        queue(db, uid, title, body, link, priority, key)
        created += 1
    return created
