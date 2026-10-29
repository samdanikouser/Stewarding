from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import timeutil
from ..audit import audit
from ..db import get_db
from ..deps import check_location, employee_place, require, scoped_locations
from ..models import AbsenceRecord, AttendanceRecord, Employee, EmployeeLocation, Location, User
from ..pagination import paginate, row

router = APIRouter(prefix="/api/absences", tags=["absences"])

AbsenceType = Literal["absent", "day_off", "sick_leave", "annual_leave", "unpaid_leave", "other_leave"]
MAX_RANGE_DAYS = 31
PAST_DAYS = 31
FUTURE_DAYS = 366
FIELDS = ("id", "employee_id", "location_id", "local_date", "absence_type", "note", "recorded_by", "created_at",
          "voided_by", "voided_at", "void_reason")


class AbsenceIn(BaseModel):
    employee_id: int
    location_id: int | None = None  # left out: where the employee works
    day: date
    day_to: date | None = None
    absence_type: AbsenceType
    note: str | None = Field(default=None, max_length=500)


class VoidIn(BaseModel):
    reason: str = Field(min_length=5, max_length=500)


def _serialize(db: Session, record: AbsenceRecord) -> dict:
    out = row(record, *FIELDS)
    out["status"] = "void" if record.voided_at else "active"
    out["employee_name"] = db.scalar(select(Employee.full_name).where(Employee.id == record.employee_id))
    out["recorded_by_name"] = db.scalar(select(Employee.full_name).where(Employee.user_id == record.recorded_by))
    return out


@router.post("", status_code=201)
def record_absence(body: AbsenceIn, user: User = Depends(require("attendance.absence")), db: Session = Depends(get_db)):
    """Records an absence, leave or day off for one day, or for every day from `day` to `day_to`; all or none."""
    emp = db.get(Employee, body.employee_id)
    if not emp or emp.status != "active":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Employee is not active at this location")
    place = employee_place(user, db, emp, body.location_id)
    last = body.day_to or body.day
    if last < body.day:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The end date is before the start date")
    if (last - body.day).days >= MAX_RANGE_DAYS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"A range covers at most {MAX_RANGE_DAYS} days")
    today = timeutil.local_date(timeutil.utc_now(), place.timezone)
    if not (today - timedelta(days=PAST_DAYS) <= body.day and last <= today + timedelta(days=FUTURE_DAYS)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"The dates must be within {PAST_DAYS} days back and {FUTURE_DAYS} days ahead")
    days = [body.day + timedelta(days=n) for n in range((last - body.day).days + 1)]
    for day in days:
        if db.scalar(select(AttendanceRecord.id).where(AttendanceRecord.employee_id == emp.id, AttendanceRecord.local_date == day)):
            raise HTTPException(status.HTTP_409_CONFLICT, f"The employee checked in on {day.isoformat()}, so that day cannot be marked")
        if db.scalar(select(AbsenceRecord.id).where(AbsenceRecord.employee_id == emp.id, AbsenceRecord.local_date == day,
                                                    AbsenceRecord.voided_at.is_(None))):
            raise HTTPException(status.HTTP_409_CONFLICT, f"{day.isoformat()} already has an absence, leave or day off recorded")
    records = [AbsenceRecord(employee_id=emp.id, location_id=place.id, local_date=day, absence_type=body.absence_type,
                             note=body.note, recorded_by=user.id) for day in days]
    try:
        db.add_all(records)
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "An absence, leave or day off is already recorded for one of those days") from None
    audit(db, user, "absence.record", "absence_record", records[0].id, None,
          {"employee_id": emp.id, "from": days[0].isoformat(), "to": days[-1].isoformat(), "type": body.absence_type})
    db.commit()
    return _serialize(db, records[0]) if len(records) == 1 else {"created": len(records), "items": [_serialize(db, r) for r in records]}


@router.get("/mine")
def my_absences(user: User = Depends(require("attendance.self")), db: Session = Depends(get_db)):
    if not user.employee:
        return []
    stmt = select(AbsenceRecord).where(AbsenceRecord.employee_id == user.employee.id, AbsenceRecord.voided_at.is_(None))
    return [_serialize(db, r) for r in db.scalars(stmt.order_by(AbsenceRecord.local_date.desc()).limit(50))]


@router.get("")
def list_absences(location_id: int | None = None, employee_id: int | None = None, date_from: date | None = None,
                  date_to: date | None = None, include_void: bool = False, page: int = 1, size: int = 25,
                  user: User = Depends(require("attendance.view")), db: Session = Depends(get_db)):
    stmt = select(AbsenceRecord)
    scope = scoped_locations(user, db)
    if location_id is not None:
        check_location(user, db, location_id)
        stmt = stmt.where(AbsenceRecord.location_id == location_id)
    elif scope is not None:
        stmt = stmt.where(AbsenceRecord.location_id.in_(scope))
    if employee_id is not None:
        stmt = stmt.where(AbsenceRecord.employee_id == employee_id)
    if date_from:
        stmt = stmt.where(AbsenceRecord.local_date >= date_from)
    if date_to:
        stmt = stmt.where(AbsenceRecord.local_date <= date_to)
    if not include_void:
        stmt = stmt.where(AbsenceRecord.voided_at.is_(None))
    total, rows = paginate(db, stmt.order_by(AbsenceRecord.local_date.desc(), AbsenceRecord.id.desc()), page, size)
    return {"total": total, "items": [_serialize(db, r[0]) for r in rows]}


@router.post("/{absence_id}/void")
def void_absence(absence_id: int, body: VoidIn, user: User = Depends(require("attendance.absence")),
                 db: Session = Depends(get_db)):
    """Cancels a recorded absence; the row stays for the history and the day can be recorded again."""
    record = db.get(AbsenceRecord, absence_id)
    if not record:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Record not found")
    check_location(user, db, record.location_id)
    if record.voided_at:
        raise HTTPException(status.HTTP_409_CONFLICT, "Record is already void")
    record.voided_by, record.voided_at, record.void_reason = user.id, timeutil.utc_now(), body.reason
    audit(db, user, "absence.void", "absence_record", record.id, {"type": record.absence_type}, {"reason": body.reason})
    db.commit()
    return _serialize(db, record)
