from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .cache import memo
from .db import get_db
from .models import EmployeeLocation, Location, User
from .permissions import MANAGER
from .security import decode_token

bearer = HTTPBearer(auto_error=False)


PASSWORD_PATHS = ("/api/auth/me", "/api/auth/change-password")


def current_user(
    request: Request, creds: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)
) -> User:
    decoded = decode_token(creds.credentials) if creds else None
    user = db.get(User, decoded[0]) if decoded else None
    if not user or not user.active or user.token_version != decoded[1]:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    if user.must_change_password and request.url.path not in PASSWORD_PATHS:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Change your password before continuing")
    if user.employee and user.employee.status != "active":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Employee account is inactive")
    return user


def permissions_of(user: User) -> set[str]:
    return {p.permission for p in user.role.permissions}


def role_names(user: User) -> set[str]:
    """The names tasks may be assigned to for this user: their own role and the tier it behaves like."""
    return {user.role.name, user.role.tier}


def require(permission: str):
    """Dependency factory: 403 unless the user's role grants `permission`."""

    def dep(user: User = Depends(current_user)) -> User:
        if permission not in permissions_of(user):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Permission denied")
        return user

    return dep


def scoped_locations(user: User, db: Session) -> set[int] | None:
    """Location ids the user may touch; None means every location (a manager, or an employee tied to no outlet)."""
    if user.role.tier == MANAGER:
        return None
    if not user.employee:
        return set()
    employee_id = user.employee.id
    placed = memo(db, ("scope", employee_id), lambda: set(db.scalars(
        select(EmployeeLocation.location_id).where(EmployeeLocation.employee_id == employee_id))))
    return placed or None  # an employee with no outlets is not tied to one: every location, including ones added later


def check_location(user: User, db: Session, location_id: int) -> None:
    """404 for an unknown location, 403 when it is outside the user's scope."""
    if not db.get(Location, location_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Location not found")
    allowed = scoped_locations(user, db)
    if allowed is not None and location_id not in allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Location not assigned to you")


def employee_place(user: User, db: Session, emp, location_id: int | None):
    """The location a record for this employee belongs to: the one named, else where they work (first by name), else the first one the user may use.

    An employee with no locations works anywhere, so the named place needs no assignment for them."""
    if location_id is not None:
        check_location(user, db, location_id)
        assigned = set(db.scalars(select(EmployeeLocation.location_id).where(EmployeeLocation.employee_id == emp.id)))
        if assigned and location_id not in assigned:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Employee is not active at this location")
        return db.get(Location, location_id)
    query = select(Location).where(Location.active.is_(True)).order_by(Location.name)
    assigned = set(db.scalars(select(EmployeeLocation.location_id).where(EmployeeLocation.employee_id == emp.id)))
    if assigned:
        query = query.where(Location.id.in_(assigned))
    allowed = scoped_locations(user, db)
    if allowed is not None:
        query = query.where(Location.id.in_(allowed))
    place = db.scalars(query).first()
    if place is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No location is available for this employee")
    return place
