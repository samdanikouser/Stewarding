import re

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..audit import audit
from ..db import get_db
from ..deps import permissions_of, require
from ..models import Role, RolePermission, User
from ..permissions import ALL_PERMISSIONS, CUSTOM_TIERS, MANAGER, PERMISSION_CATALOG, ROLE_PERMISSIONS

router = APIRouter(prefix="/api/roles", tags=["roles"])


def _manager_only(user: User = Depends(require("settings.manage"))) -> User:
    if user.role.tier != MANAGER:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a manager can change roles")
    return user


def _known_tier(value: str | None) -> str | None:
    if value is not None and value not in CUSTOM_TIERS:
        raise ValueError("A custom role behaves like a supervisor or a steward")
    return value


def _known_permissions(value: list[str] | None) -> list[str] | None:
    if value is None:
        return None
    unknown = sorted(set(value) - set(ALL_PERMISSIONS))
    if unknown:
        raise ValueError(f"Unknown permission: {', '.join(unknown)}")
    return sorted(set(value))


class RoleIn(BaseModel):
    label: str = Field(min_length=2, max_length=80)
    tier: str
    permissions: list[str] = Field(min_length=1)

    _tier = field_validator("tier")(_known_tier)
    _permissions = field_validator("permissions")(_known_permissions)


class RoleUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=2, max_length=80)
    tier: str | None = None
    permissions: list[str] | None = Field(default=None, min_length=1)

    _tier = field_validator("tier")(_known_tier)
    _permissions = field_validator("permissions")(_known_permissions)


def _users_per_role(db: Session) -> dict[int, int]:
    return dict(db.execute(select(User.role_id, func.count()).group_by(User.role_id)).all())


def _dict(role: Role, users: int) -> dict:
    return {"id": role.id, "name": role.name, "label": role.label or role.name, "tier": role.tier, "builtin": role.builtin,
            "permissions": sorted(p.permission for p in role.permissions), "users": users,
            "defaults": sorted(ROLE_PERMISSIONS[role.name]) if role.builtin and role.name in ROLE_PERMISSIONS else None}


def _name_for(db: Session, label: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")[:34] or "role"
    name, n = base, 1
    while db.scalar(select(Role.id).where(Role.name == name)):
        n += 1
        name = f"{base}_{n}"
    return name


def _label_taken(db: Session, label: str, exclude_id: int | None = None) -> bool:
    shown = func.lower(func.coalesce(Role.label, Role.name))
    return db.scalar(select(Role.id).where(or_(shown == label.lower(), func.lower(Role.name) == label.lower()), Role.id != (exclude_id or 0))) is not None


@router.get("")
def list_roles(user: User = Depends(_manager_only), db: Session = Depends(get_db)):
    counts = _users_per_role(db)
    return [_dict(r, counts.get(r.id, 0)) for r in db.scalars(select(Role).order_by(Role.builtin.desc(), Role.label, Role.name))]


@router.get("/catalog")
def catalog(user: User = Depends(_manager_only)):
    return {"tiers": list(CUSTOM_TIERS),
            "groups": [{"group": group, "permissions": [{"key": k, "label": label} for k, label in entries]} for group, entries in PERMISSION_CATALOG]}


@router.get("/options")
def options(user: User = Depends(require("employee.manage")), db: Session = Depends(get_db)):
    """Roles the caller may give to an employee: every role for a manager, otherwise only those within their own access."""
    mine = permissions_of(user)
    return [{"name": r.name, "label": r.label or r.name, "tier": r.tier, "builtin": r.builtin}
            for r in db.scalars(select(Role).order_by(Role.builtin.desc(), Role.label, Role.name))
            if user.role.tier == MANAGER or (r.tier != MANAGER and {p.permission for p in r.permissions} <= mine)]


@router.post("", status_code=201)
def create_role(body: RoleIn, user: User = Depends(_manager_only), db: Session = Depends(get_db)):
    label = " ".join(body.label.split())
    if _label_taken(db, label):
        raise HTTPException(status.HTTP_409_CONFLICT, "A role with that name already exists")
    role = Role(name=_name_for(db, label), label=label, tier=body.tier, builtin=False)
    role.permissions = [RolePermission(permission=p) for p in body.permissions]
    db.add(role)
    db.flush()
    audit(db, user, "role.create", "role", role.id, None, {"label": role.label, "tier": role.tier, "permissions": body.permissions})
    db.commit()
    return _dict(role, 0)


@router.put("/{role_id}")
def update_role(role_id: int, body: RoleUpdate, user: User = Depends(_manager_only), db: Session = Depends(get_db)):
    role = db.get(Role, role_id)
    if not role:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Role not found")
    if role.name == MANAGER:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The manager role always has full access and cannot be changed")
    data = body.model_dump(exclude_unset=True)
    if role.builtin and data.get("tier", role.tier) != role.tier:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A built-in role keeps its behaviour; make a custom role to choose another")
    if "label" in data:
        data["label"] = " ".join(data["label"].split())
        if _label_taken(db, data["label"], role.id):
            raise HTTPException(status.HTTP_409_CONFLICT, "A role with that name already exists")
    before = {"label": role.label, "tier": role.tier, "permissions": sorted(p.permission for p in role.permissions)}
    if "label" in data:
        role.label = data["label"]
    if "tier" in data:
        role.tier = data["tier"]
    if "permissions" in data:
        role.permissions = [RolePermission(permission=p) for p in data["permissions"]]
    db.flush()
    audit(db, user, "role.update", "role", role.id, before,
          {"label": role.label, "tier": role.tier, "permissions": sorted(p.permission for p in role.permissions)})
    db.commit()
    return _dict(role, _users_per_role(db).get(role.id, 0))


@router.delete("/{role_id}")
def delete_role(role_id: int, user: User = Depends(_manager_only), db: Session = Depends(get_db)):
    role = db.get(Role, role_id)
    if not role:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Role not found")
    if role.builtin:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The built-in roles cannot be deleted")
    if _users_per_role(db).get(role.id):
        raise HTTPException(status.HTTP_409_CONFLICT, "People still have this role; move them to another role first")
    audit(db, user, "role.delete", "role", role.id, {"label": role.label}, None)
    db.delete(role)
    db.commit()
    return {"deleted": role_id}
