from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import audit
from ..services.deletion import delete_if_unused
from ..db import get_db
from ..deps import current_user, require
from ..models import LookupValue, User
from ..pagination import row
from ..services.inventory import norm

router = APIRouter(prefix="/api/lookups", tags=["lookups"])

Kind = Literal["job_title", "checklist_category", "breakage_reason", "corrective_action", "monitoring_type"]
KINDS = ("job_title", "checklist_category", "breakage_reason", "corrective_action", "monitoring_type")


class LookupIn(BaseModel):
    kind: Kind
    value: str = Field(min_length=2, max_length=120)

    @field_validator("value")
    @classmethod
    def _not_blank(cls, value):
        value = " ".join(value.split())
        if len(value) < 2:
            raise ValueError("Enter at least two characters")
        return value


class LookupUpdate(BaseModel):
    value: str | None = Field(default=None, min_length=2, max_length=120)
    active: bool | None = None


@router.get("")
def list_lookups(kind: Kind | None = None, include_inactive: bool = False, user: User = Depends(current_user),
                 db: Session = Depends(get_db)):
    """Every signed-in user reads the lists, because forms need them; only managers change them."""
    stmt = select(LookupValue).order_by(LookupValue.kind, LookupValue.value)
    if kind:
        stmt = stmt.where(LookupValue.kind == kind)
    if not include_inactive:
        stmt = stmt.where(LookupValue.active.is_(True))
    rows = [row(v, "id", "kind", "value", "active") for v in db.scalars(stmt)]
    return rows if kind else {k: [r for r in rows if r["kind"] == k] for k in KINDS}


@router.post("", status_code=201)
def create_lookup(body: LookupIn, user: User = Depends(require("settings.manage")), db: Session = Depends(get_db)):
    value = " ".join(body.value.split())
    existing = db.scalar(select(LookupValue).where(LookupValue.kind == body.kind, LookupValue.value_key == norm(value)))
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{existing.value} already exists in this list")
    item = LookupValue(kind=body.kind, value=value, value_key=norm(value))
    db.add(item)
    db.flush()
    audit(db, user, "lookup.create", "lookup_value", item.id, None, {"kind": body.kind, "value": value})
    db.commit()
    return row(item, "id", "kind", "value", "active")


@router.put("/{lookup_id}")
def update_lookup(lookup_id: int, body: LookupUpdate, user: User = Depends(require("settings.manage")),
                  db: Session = Depends(get_db)):
    item = db.get(LookupValue, lookup_id)
    if not item:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Value not found")
    data = body.model_dump(exclude_unset=True)
    if "value" in data:
        data["value"] = " ".join(data["value"].split())
        clash = db.scalar(select(LookupValue).where(LookupValue.kind == item.kind, LookupValue.value_key == norm(data["value"]),
                                                    LookupValue.id != item.id))
        if clash:
            raise HTTPException(status.HTTP_409_CONFLICT, f"{clash.value} already exists in this list")
    before = {k: getattr(item, k) for k in data}
    for key, value in data.items():
        setattr(item, key, value)
    if "value" in data:
        item.value_key = norm(data["value"])
    audit(db, user, "lookup.update", "lookup_value", item.id, before, data)
    db.commit()
    return row(item, "id", "kind", "value", "active")


@router.delete("/{lookup_id}")
def delete_lookup(lookup_id: int, user: User = Depends(require("settings.manage")), db: Session = Depends(get_db)):
    item = db.get(LookupValue, lookup_id)
    if not item:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Value not found")
    before = {"kind": item.kind, "value": item.value}
    delete_if_unused(db, item, item.value)
    audit(db, user, "lookup.delete", "lookup_value", lookup_id, before, None)
    db.commit()
    return {"deleted": lookup_id}
