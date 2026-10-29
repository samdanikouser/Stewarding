from datetime import date, time
from math import gcd
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import timeutil
from ..audit import audit
from ..services.deletion import delete_if_unused
from ..db import get_db
from ..deps import check_location, require, scoped_locations
from ..models import (AbsenceRecord, AttendanceRecord, Employee, EmployeeLocation, Location, Shift, ShiftAssignment,
                      User)
from ..pagination import row

router = APIRouter(prefix="/api/roster", tags=["roster"])


class ShiftIn(BaseModel):
    kind: Literal["work", "weekoff"] = "work"
    name: str = Field(min_length=2, max_length=60)
    start_time: time
    end_time: time
    grace_minutes: int = Field(default=10, ge=0, le=120)
    break_minutes: int = Field(default=0, ge=0, le=240)
    overtime_after_minutes: int | None = Field(default=None, ge=0, le=1440)
    active: bool = True

    @model_validator(mode="after")
    def _hours(self):
        if self.kind == "work":
            minutes = (self.end_time.hour * 60 + self.end_time.minute) - (self.start_time.hour * 60 + self.start_time.minute)
            length = minutes % 1440
            if length == 0:
                raise ValueError("A working shift needs different start and end times")
            if self.break_minutes >= length:
                raise ValueError("The break must be shorter than the shift")
        return self


class AssignmentIn(BaseModel):
    employee_id: int
    shift_id: int
    location_id: int | None = None  # left out: the first location the employee works at
    weekdays: list[int] = Field(min_length=1)
    valid_from: date
    valid_to: date | None = None
    cycle_weeks: int = Field(default=1, ge=1, le=4)
    cycle_week: int = Field(default=0, ge=0, le=3)

    @model_validator(mode="after")
    def _range(self):
        if self.valid_to is not None and self.valid_to < self.valid_from:
            raise ValueError("The end date cannot be before the start date")
        if self.cycle_week >= self.cycle_weeks:
            raise ValueError("The week of the cycle must be within the cycle")
        return self


SHIFT_FIELDS = ("id", "kind", "name", "start_time", "end_time", "grace_minutes", "break_minutes",
                "overtime_after_minutes", "active")


def _shift_values(body: ShiftIn) -> dict:
    """A week off has no working hours, late rule, break or overtime."""
    values = body.model_dump()
    if body.kind == "weekoff":
        values.update(start_time=time(0, 0), end_time=time(0, 0), grace_minutes=0, break_minutes=0, overtime_after_minutes=None)
    return values


@router.get("/shifts")
def list_shifts(user: User = Depends(require("roster.view")), db: Session = Depends(get_db)):
    return [row(s, *SHIFT_FIELDS) for s in db.scalars(select(Shift).order_by(Shift.kind, Shift.start_time))]


def _ensure_unique_shift(db: Session, name: str, own_id: int | None = None) -> None:
    clash = select(Shift.id).where(func.lower(Shift.name) == " ".join(name.split()).lower())
    if own_id is not None:
        clash = clash.where(Shift.id != own_id)
    if db.scalar(clash):
        raise HTTPException(status.HTTP_409_CONFLICT, "A shift with this name already exists")


@router.post("/shifts", status_code=201)
def create_shift(body: ShiftIn, user: User = Depends(require("roster.manage")), db: Session = Depends(get_db)):
    _ensure_unique_shift(db, body.name)
    shift = Shift(**_shift_values(body))
    db.add(shift)
    db.flush()
    audit(db, user, "shift.create", "shift", shift.id, None, body.model_dump(mode="json"))
    db.commit()
    return row(shift, *SHIFT_FIELDS)


@router.put("/shifts/{shift_id}")
def update_shift(shift_id: int, body: ShiftIn, user: User = Depends(require("roster.manage")),
                 db: Session = Depends(get_db)):
    shift = db.get(Shift, shift_id)
    if not shift:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Shift not found")
    _ensure_unique_shift(db, body.name, shift.id)
    before = row(shift, *SHIFT_FIELDS)
    if body.kind != shift.kind and db.scalar(select(ShiftAssignment.id).where(ShiftAssignment.shift_id == shift.id)):
        raise HTTPException(status.HTTP_409_CONFLICT, "A shift that is already assigned cannot change between working shift and week off")
    for key, value in _shift_values(body).items():
        setattr(shift, key, value)
    audit(db, user, "shift.update", "shift", shift.id, {k: str(v) for k, v in before.items()},
          body.model_dump(mode="json"))
    db.commit()
    return row(shift, *SHIFT_FIELDS)


@router.get("/assignments")
def list_assignments(location_id: int | None = None, employee_id: int | None = None,
                     user: User = Depends(require("roster.view")), db: Session = Depends(get_db)):
    stmt = select(ShiftAssignment).where(or_(ShiftAssignment.valid_to.is_(None),
                                             ShiftAssignment.valid_to >= timeutil.utc_now().date()))
    allowed = scoped_locations(user, db)
    if location_id is not None:
        check_location(user, db, location_id)
        stmt = stmt.where(ShiftAssignment.location_id == location_id)
    elif allowed is not None:
        stmt = stmt.where(ShiftAssignment.location_id.in_(allowed))
    if employee_id is not None:
        stmt = stmt.where(ShiftAssignment.employee_id == employee_id)
    return [row(a, "id", "employee_id", "shift_id", "location_id", "weekday", "valid_from", "valid_to", "cycle_weeks", "cycle_week")
            for a in db.scalars(stmt.order_by(ShiftAssignment.location_id, ShiftAssignment.weekday))]


class EndIn(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=7)


def _meeting(db: Session, body: "AssignmentIn", *conditions) -> bool:
    """Whether the employee already has an assignment matching `conditions` that falls in the same weeks as the new one."""
    found = db.execute(select(ShiftAssignment.cycle_weeks, ShiftAssignment.cycle_week).join(Shift, Shift.id == ShiftAssignment.shift_id)
                       .where(ShiftAssignment.employee_id == body.employee_id, *conditions))
    return any((week - body.cycle_week) % gcd(weeks, body.cycle_weeks) == 0 for weeks, week in found)


def _fill_location(db: Session, body: AssignmentIn) -> None:
    if body.location_id is None:
        own = select(EmployeeLocation.location_id).where(EmployeeLocation.employee_id == body.employee_id)
        query = select(Location.id).where(Location.active.is_(True)).order_by(Location.name)
        body.location_id = db.scalar(query.where(Location.id.in_(own))) or db.scalar(query)  # nothing set: the first location


def _check_assignment(db: Session, body: AssignmentIn, ignore: set[int]) -> None:
    """Refuses an assignment the employee cannot take: a retired shift, another location, a repeat or a clash; `ignore` are rows being replaced."""
    if any(d < 0 or d > 6 for d in body.weekdays):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Weekdays must be 0 (Monday) to 6 (Sunday)")
    shift = db.get(Shift, body.shift_id)
    if not shift or not shift.active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown or retired shift")
    works_here = db.scalar(select(EmployeeLocation.employee_id).where(
        EmployeeLocation.employee_id == body.employee_id, EmployeeLocation.location_id == body.location_id))
    if works_here is None and db.scalar(select(EmployeeLocation.employee_id).where(EmployeeLocation.employee_id == body.employee_id)) is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Employee is not assigned to that location")
    overlaps = (ShiftAssignment.weekday.in_(set(body.weekdays)), ShiftAssignment.id.not_in(ignore),
                or_(ShiftAssignment.valid_to.is_(None), ShiftAssignment.valid_to >= body.valid_from),
                ShiftAssignment.valid_from <= (body.valid_to or date.max))
    repeat = _meeting(db, body, ShiftAssignment.shift_id == body.shift_id, ShiftAssignment.location_id == body.location_id, *overlaps)
    if repeat:
        raise HTTPException(status.HTTP_409_CONFLICT, f"The employee already has {shift.name} on one of those days; end it first")
    opposite = "work" if shift.kind == "weekoff" else "weekoff"
    clash = _meeting(db, body, Shift.kind == opposite, *overlaps)
    if clash:
        raise HTTPException(status.HTTP_409_CONFLICT, "The employee already has a "
                            + ("working shift" if opposite == "work" else "week off") + " on one of those days; end it first")


def _insert_assignments(db: Session, body: AssignmentIn) -> list[int]:
    created = []
    try:
        for weekday in sorted(set(body.weekdays)):
            a = ShiftAssignment(employee_id=body.employee_id, shift_id=body.shift_id, location_id=body.location_id,
                                weekday=weekday, valid_from=body.valid_from, valid_to=body.valid_to,
                                cycle_weeks=body.cycle_weeks, cycle_week=body.cycle_week)
            db.add(a)
            db.flush()
            created.append(a.id)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Assignment already exists") from None
    return created


@router.post("/assignments", status_code=201)
def create_assignments(body: AssignmentIn, user: User = Depends(require("roster.manage")),
                       db: Session = Depends(get_db)):
    _fill_location(db, body)
    _check_assignment(db, body, set())
    created = _insert_assignments(db, body)
    audit(db, user, "roster.assign", "shift_assignment", created[0], None, body.model_dump(mode="json"))
    db.commit()
    return {"ids": created}


class ChangeIn(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=7)
    shift_id: int
    weekdays: list[int] = Field(min_length=1)
    valid_from: date
    valid_to: date | None = None
    cycle_weeks: int = Field(default=1, ge=1, le=4)
    cycle_week: int = Field(default=0, ge=0, le=3)

    @model_validator(mode="after")
    def _range(self):
        if self.valid_to is not None and self.valid_to < self.valid_from:
            raise ValueError("The end date cannot be before the start date")
        if self.cycle_week >= self.cycle_weeks:
            raise ValueError("The week of the cycle must be within the cycle")
        return self


def _load_group(db: Session, user: User, ids: list[int]) -> list[ShiftAssignment]:
    rows = list(db.scalars(select(ShiftAssignment).where(ShiftAssignment.id.in_(ids))))
    if len(rows) != len(set(ids)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assignment not found")
    if len({(a.employee_id, a.location_id) for a in rows}) > 1:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "These assignments belong to different people or locations")
    check_location(user, db, rows[0].location_id)
    return rows


@router.put("/assignments")
def change_assignments(body: ChangeIn, user: User = Depends(require("roster.manage")), db: Session = Depends(get_db)):
    """Replaces one employee's group of weekly assignments with new days, shift and dates, checking them as a new assignment would be."""
    old = _load_group(db, user, body.ids)
    new = AssignmentIn(employee_id=old[0].employee_id, location_id=old[0].location_id, shift_id=body.shift_id,
                       weekdays=body.weekdays, valid_from=body.valid_from, valid_to=body.valid_to,
                       cycle_weeks=body.cycle_weeks, cycle_week=body.cycle_week)
    _check_assignment(db, new, {a.id for a in old})
    before = {"ids": sorted(a.id for a in old), "shift_id": old[0].shift_id, "weekdays": sorted(a.weekday for a in old),
              "valid_from": old[0].valid_from.isoformat(), "valid_to": old[0].valid_to.isoformat() if old[0].valid_to else None,
              "cycle_weeks": old[0].cycle_weeks, "cycle_week": old[0].cycle_week}
    for a in old:
        db.delete(a)
    db.flush()
    created = _insert_assignments(db, new)
    audit(db, user, "roster.update", "shift_assignment", created[0], before, new.model_dump(mode="json"))
    db.commit()
    return {"ids": created}


@router.post("/assignments/remove")
def remove_assignments(body: EndIn, user: User = Depends(require("roster.manage")), db: Session = Depends(get_db)):
    """Deletes a group of assignments entirely, as if they had never been made."""
    old = _load_group(db, user, body.ids)
    before = {"ids": sorted(a.id for a in old), "shift_id": old[0].shift_id, "weekdays": sorted(a.weekday for a in old)}
    for a in old:
        db.delete(a)
    audit(db, user, "roster.remove", "shift_assignment", old[0].id, before, None)
    db.commit()
    return {"removed": len(old)}


@router.post("/assignments/end")
def end_assignments(body: EndIn, user: User = Depends(require("roster.manage")), db: Session = Depends(get_db)):
    """Ends every listed assignment today, or on its start date when it has not started yet."""
    found = {a.id: a for a in db.scalars(select(ShiftAssignment).where(ShiftAssignment.id.in_(body.ids)))}
    if len(found) != len(set(body.ids)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assignment not found")
    today = timeutil.utc_now().date()
    for a in found.values():
        check_location(user, db, a.location_id)
        a.valid_to = max(today, a.valid_from)
    audit(db, user, "roster.end", "shift_assignment", min(found), None, {"ids": sorted(found), "valid_to": today.isoformat()})
    db.commit()
    return {"ended": len(found)}


@router.delete("/assignments/{assignment_id}")
def end_assignment(assignment_id: int, user: User = Depends(require("roster.manage")), db: Session = Depends(get_db)):
    a = db.get(ShiftAssignment, assignment_id)
    if not a:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assignment not found")
    a.valid_to = timeutil.utc_now().date()
    audit(db, user, "roster.end", "shift_assignment", a.id, None, {"valid_to": a.valid_to.isoformat()})
    db.commit()
    return {"ok": True}


@router.get("/today")
def today(location_id: int, user: User = Depends(require("roster.view")), db: Session = Depends(get_db)):
    check_location(user, db, location_id)
    location = db.get(Location, location_id)
    now = timeutil.utc_now()
    day = timeutil.local_date(now, location.timezone)
    rows = db.execute(
        select(ShiftAssignment, Employee, Shift)
        .join(Employee, Employee.id == ShiftAssignment.employee_id)
        .join(Shift, Shift.id == ShiftAssignment.shift_id)
        .where(ShiftAssignment.location_id == location_id, ShiftAssignment.weekday == day.weekday(), Employee.status == "active")
    ).all()
    rows = [(a, e, s) for a, e, s in rows if a.applies_on(day)]
    attended = {r.employee_id: r for r in db.scalars(select(AttendanceRecord).where(
        AttendanceRecord.location_id == location_id, AttendanceRecord.local_date == day))}
    absences = {a.employee_id: a for a in db.scalars(select(AbsenceRecord).where(
        AbsenceRecord.location_id == location_id, AbsenceRecord.local_date == day, AbsenceRecord.voided_at.is_(None)))}
    elsewhere = dict(db.execute(
        select(AttendanceRecord.employee_id, Location.name).join(Location, Location.id == AttendanceRecord.location_id)
        .where(AttendanceRecord.location_id != location_id, AttendanceRecord.local_date == day,
               AttendanceRecord.employee_id.in_([e.id for _, e, _ in rows]))).all())
    return [{
        "employee_id": e.id, "name": e.full_name, "shift": s.name, "elsewhere": elsewhere.get(e.id), "shift_start": s.start_time.isoformat(),
        "day_type": "week_off" if s.kind == "weekoff" or (e.id in absences and absences[e.id].absence_type == "day_off")
        else ("absence" if e.id in absences and e.id not in attended else "work"),
        "absence_type": absences[e.id].absence_type if e.id in absences else None,
        "checked_in": e.id in attended, "late_minutes": attended[e.id].late_minutes if e.id in attended else 0,
        "on_duty": e.id in attended and attended[e.id].check_out_at is None,
    } for e, s in {(e.id, s.id): (e, s) for _, e, s in rows}.values()]


@router.delete("/shifts/{shift_id}")
def delete_shift(shift_id: int, user: User = Depends(require("roster.manage")), db: Session = Depends(get_db)):
    shift = db.get(Shift, shift_id)
    if not shift:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Shift not found")
    before = {"name": shift.name, "kind": shift.kind}
    delete_if_unused(db, shift, shift.name)
    audit(db, user, "shift.delete", "shift", shift_id, before, None)
    db.commit()
    return {"deleted": shift_id}
