"""Days a location (or every location) is closed: its checklist tasks and monitoring checks are not expected and send no alerts."""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .. import timeutil
from ..audit import audit
from ..db import get_db
from ..deps import require
from ..models import ChecklistInstance, ClosedDay, Location, User
from ..pagination import row
from ..services.checklists import OPEN

router = APIRouter(prefix="/api/closures", tags=["closed days"])

MAX_DAYS = 90


class ClosureIn(BaseModel):
    location_id: int | None = None  # none: every location
    start_date: date
    end_date: date
    reason: str = Field(min_length=2, max_length=200)

    @model_validator(mode="after")
    def _range(self):
        if self.end_date < self.start_date:
            raise ValueError("The last day cannot be before the first day")
        if (self.end_date - self.start_date).days >= MAX_DAYS:
            raise ValueError(f"A closure covers at most {MAX_DAYS} days")
        return self


def _serialize(db: Session, c: ClosedDay) -> dict:
    place = db.get(Location, c.location_id).name if c.location_id else None
    return {**row(c, "id", "location_id", "start_date", "end_date", "reason", "created_at"), "location": place or "All locations"}


@router.get("")
def list_closures(user: User = Depends(require("settings.manage")), db: Session = Depends(get_db)):
    """Closures from the last month onward, soonest first."""
    since = timeutil.utc_now().date() - timedelta(days=31)
    return [_serialize(db, c) for c in db.scalars(select(ClosedDay).where(ClosedDay.end_date >= since).order_by(ClosedDay.start_date, ClosedDay.id))]


@router.post("", status_code=201)
def add_closure(body: ClosureIn, user: User = Depends(require("settings.manage")), db: Session = Depends(get_db)):
    if body.location_id is not None and not db.get(Location, body.location_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Location not found")
    closure = ClosedDay(location_id=body.location_id, start_date=body.start_date, end_date=body.end_date, reason=" ".join(body.reason.split()), created_by=user.id)
    db.add(closure)
    db.flush()
    # tasks already made for those days are waived, so they do not sit there overdue
    stmt = (update(ChecklistInstance).where(ChecklistInstance.status.in_(OPEN + ("overdue",)), ChecklistInstance.local_date >= body.start_date,
                                            ChecklistInstance.local_date <= body.end_date)
            .values(status="waived", waive_reason=f"Closed: {closure.reason}"))
    if body.location_id is not None:
        stmt = stmt.where(ChecklistInstance.location_id == body.location_id)
    waived = db.execute(stmt).rowcount
    audit(db, user, "closure.add", "closed_day", closure.id, None, {**body.model_dump(mode="json"), "tasks_waived": waived})
    db.commit()
    return {**_serialize(db, closure), "tasks_waived": waived}


@router.delete("/{closure_id}")
def remove_closure(closure_id: int, user: User = Depends(require("settings.manage")), db: Session = Depends(get_db)):
    closure = db.get(ClosedDay, closure_id)
    if not closure:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Closure not found")
    audit(db, user, "closure.remove", "closed_day", closure.id, {"start": closure.start_date.isoformat(), "end": closure.end_date.isoformat()}, None)
    db.delete(closure)
    db.commit()
    return {"ok": True}
