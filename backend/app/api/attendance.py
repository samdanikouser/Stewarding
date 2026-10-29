import base64
import binascii
import secrets
import uuid
from datetime import date, datetime, time, timedelta
from math import asin, cos, dist, isfinite, radians, sin, sqrt
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import timeutil
from ..audit import audit
from ..config import settings
from ..db import get_db
from ..deps import check_location, employee_place, permissions_of, require, role_names, scoped_locations
from ..models import (AbsenceRecord, AttendanceCorrection, AttendanceRecord, ChecklistInstance, ChecklistTask, Employee,
                      EmployeeLocation, FaceChallenge, Location, Shift, ShiftAssignment, User)
from ..pagination import iso, paginate, row
from .absences import PAST_DAYS
from ..services.checklists import DONE
from ..services.deletion import blockers
from ..services.settings import get_setting
from ..services.notify import notify
from ..services.organization import get_organization

router = APIRouter(prefix="/api/attendance", tags=["attendance"])

MISSED_CHECKOUT_HOURS = 16
CHALLENGE_STEPS = ("turn_left", "turn_right")
CHALLENGE_LENGTH = 3
CHALLENGE_TTL_S = 300  # long enough to type an exception reason after the check
CHALLENGE_MIN_S = 3  # three turns and a straight look cannot honestly be done faster
MAX_SNAPSHOT_BYTES = 150_000
FIELDS = ("id", "employee_id", "location_id", "shift_id", "local_date", "check_in_at", "check_out_at",
          "late_minutes", "payable_minutes", "overtime_minutes", "exception_reason")


class Position(BaseModel):
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    accuracy: float | None = Field(default=None, ge=0, le=100000)
    face: list[float] | None = Field(default=None, min_length=128, max_length=128)
    challenge: str | None = Field(default=None, max_length=64)
    liveness: list[str] | None = Field(default=None, max_length=10)
    snapshot: str | None = Field(default=None, max_length=250_000)  # base64 JPEG taken at the live check


class CheckInIn(Position):
    location_id: int | None = None  # left out when attendance is not by location: the server works it out from the position


class CheckOutIn(Position):
    exception_reason: str | None = Field(default=None, max_length=500)


def _place_by_position(db: Session, user: User, emp: Employee, where: Position) -> tuple[Location, float | None]:
    """When staff do not choose a location: today's rostered one first, else any they may work at, whichever the position fits."""
    allowed = scoped_locations(user, db)
    query = select(Location).where(Location.active.is_(True)).order_by(Location.name)
    if allowed is not None:
        query = query.where(Location.id.in_(allowed))
    places = list(db.scalars(query))
    rostered = [r["location_id"] for r in rostered_today(db, emp, timeutil.utc_now()) if not r["week_off"]]
    places.sort(key=lambda p: p.id not in rostered)
    if not places:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You are not assigned to a location")
    first_error = None
    for place in places:
        try:
            return place, _enforce_geofence(db, place, where, "check in")
        except HTTPException as err:
            first_error = first_error or err
    raise first_error


def _distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    a = sin(radians(lat2 - lat1) / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371000 * asin(sqrt(a))


def _enforce_geofence(db: Session, location: Location, where: Position, action: str) -> float | None:
    """Refuses a position outside the area or too vague to trust, and returns the distance from the centre."""
    if not location.geofence_radius_m:
        return None
    if where.latitude is None or where.longitude is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Allow location access in your browser to {action} at {location.name}")
    limit = get_setting(db, "attendance.max_accuracy_m")
    if limit and where.accuracy and where.accuracy > limit:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Your location is too imprecise (within {round(where.accuracy)} m, the limit is {limit} m). Move to open sky or turn Wi-Fi on and try again")
    away = _distance_m(where.latitude, where.longitude, location.latitude, location.longitude)
    if away > location.geofence_radius_m:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"You are about {round(away)} m from {location.name}. You can {action} only within {location.geofence_radius_m} m")
    return away


def _verify_face(db: Session, emp: Employee, where: Position, action: str) -> float | None:
    """When face verification is on, the live face must be close enough to the enrolled one; returns the distance."""
    if not get_setting(db, "attendance.face_required"):
        return None
    if emp.face_descriptor is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Your face is not enrolled yet. Ask your manager to enroll it")
    if where.face is None or not all(isfinite(v) for v in where.face):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Face verification is required to {action}")
    if get_setting(db, "attendance.face_liveness"):
        _spend_challenge(db, emp, where, action)
    away = dist(where.face, emp.face_descriptor)
    if away > get_setting(db, "attendance.face_match_max") / 100:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Your face did not match. Face the camera in good light and try again")
    return away


def _liveness_on(db: Session) -> bool:
    return bool(get_setting(db, "attendance.face_required") and get_setting(db, "attendance.face_liveness"))


def _spend_challenge(db: Session, emp: Employee, where: Position, action: str) -> None:
    """The head-turn challenge must be this person's, unused, current, not suspiciously quick and shown in the order given."""
    challenge = db.scalar(select(FaceChallenge).where(FaceChallenge.token == (where.challenge or ""), FaceChallenge.employee_id == emp.id))
    if challenge is None or challenge.used_at is not None or challenge.action != action.split()[-1]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The camera check has expired or was already used. Start it again")
    now = timeutil.utc_now()
    challenge.used_at = now
    db.commit()  # one attempt spends it, whether the face matches or not
    elapsed = (now - challenge.created_at).total_seconds()
    if elapsed > CHALLENGE_TTL_S:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The camera check took too long. Start it again")
    if elapsed < CHALLENGE_MIN_S:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That was too quick to be a live check. Start it again")
    if where.liveness != challenge.steps:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The head movements did not match the check. Start it again")


def _snapshot_bytes(db: Session, where: Position) -> bytes | None:
    """The photo taken at the live check, checked before anything is spent; none when live checks are off."""
    if not _liveness_on(db):
        return None
    try:
        data = base64.b64decode(where.snapshot or "", validate=True)
    except binascii.Error:
        data = b""
    if not data.startswith(b"\xff\xd8\xff") or len(data) > MAX_SNAPSHOT_BYTES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A camera snapshot is needed with the face check")
    return data


def _write_snapshot(data: bytes | None) -> str | None:
    if data is None:
        return None
    folder = Path(settings.upload_dir) / "faces"
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}.jpg"
    (folder / name).write_bytes(data)
    return name


def _geo_evidence(db: Session, emp: Employee, where: Position, distance: float | None, now: datetime) -> dict | None:
    """The position kept with a punch, with a flag for each sign that it may not be real."""
    if where.latitude is None or where.longitude is None:
        return None
    flags = []
    if not where.accuracy:
        flags.append("No accuracy reported")
    last = db.scalar(select(AttendanceRecord).where(AttendanceRecord.employee_id == emp.id).order_by(AttendanceRecord.id.desc()))
    earlier = None
    if last:
        earlier = ((last.check_out_geo, last.check_out_at) if last.check_out_geo else (last.check_in_geo, last.check_in_at))
    if earlier and earlier[0]:
        geo, when = earlier
        if (round(geo["latitude"], 6), round(geo["longitude"], 6)) == (round(where.latitude, 6), round(where.longitude, 6)):
            flags.append("Same position as the last punch")
        else:
            km = _distance_m(geo["latitude"], geo["longitude"], where.latitude, where.longitude) / 1000
            hours = max((now - when).total_seconds() / 3600, 1 / 60)
            if km > 2 and km / hours > 150:
                flags.append("Impossible travel since the last punch")
    return {"latitude": where.latitude, "longitude": where.longitude, "accuracy": where.accuracy,
            "distance": None if distance is None else round(distance), "flags": flags}


class CorrectionIn(BaseModel):
    field: Literal["check_in_at", "check_out_at"]
    new_value: datetime
    reason: str = Field(min_length=5, max_length=500)

    @field_validator("new_value")
    @classmethod
    def _needs_offset(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("new_value must include a timezone offset")
        return v


MANUAL_DAYS_BACK = 62
MANUAL_PREFIX = "Manual entry by manager"


class ManualIn(BaseModel):
    employee_id: int
    location_id: int | None = None  # left out: where the employee works
    day: date
    check_in_time: time
    check_out_time: time
    reason: str = Field(min_length=5, max_length=500)


def _employee(user: User) -> Employee:
    if not user.employee:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No employee profile on this account")
    return user.employee


def _open_record(db: Session, emp: Employee) -> AttendanceRecord | None:
    return db.scalar(select(AttendanceRecord).where(AttendanceRecord.employee_id == emp.id,
                                                    AttendanceRecord.open_flag == 1))


def _pick_shift(db: Session, emp: Employee, location: Location, now: datetime) -> tuple[Shift | None, date]:
    """The shift a check-in belongs to and the day that shift started on.

    That is today's shift starting nearest to now, or yesterday's overnight shift that has not ended yet: someone
    arriving at 00:30 for a 17:00 to 05:00 shift is late for last night's shift, not early for tonight's."""
    today = timeutil.local_date(now, location.timezone)
    found = []
    for day in (today - timedelta(days=1), today):
        for shift, assignment in db.execute(
                select(Shift, ShiftAssignment).join(ShiftAssignment, ShiftAssignment.shift_id == Shift.id)
                .where(ShiftAssignment.employee_id == emp.id, ShiftAssignment.location_id == location.id,
                       ShiftAssignment.weekday == day.weekday(), Shift.active.is_(True), Shift.kind == "work")):
            if not assignment.applies_on(day):
                continue
            if day < today and not (shift.end_time <= shift.start_time and now <= timeutil.shift_end_utc(day, shift.start_time, shift.end_time, location.timezone)):
                continue  # yesterday counts only while its overnight shift is still running
            found.append((shift, day))
    if not found:
        return None, today
    return min(found, key=lambda f: abs((now - timeutil.local_to_utc(f[1], f[0].start_time, location.timezone)).total_seconds()))


def rostered_today(db: Session, emp: Employee, now: datetime) -> list[dict]:
    """Where and when the employee is rostered today, or marked off, at each location, earliest shift first.

    Includes yesterday's overnight shift while it is still running, so the check-in screen shows the shift they are really on."""
    found = db.execute(
        select(ShiftAssignment, Shift, Location).join(Shift, Shift.id == ShiftAssignment.shift_id)
        .join(Location, Location.id == ShiftAssignment.location_id)
        .where(ShiftAssignment.employee_id == emp.id, Shift.active.is_(True), Location.active.is_(True)))
    today: dict[tuple[int, int], tuple[Shift, Location]] = {}
    for assignment, shift, location in found:
        day = timeutil.local_date(now, location.timezone)
        if assignment.applies_on(day):
            today[(shift.id, location.id)] = (shift, location)
        elif (shift.kind == "work" and shift.end_time <= shift.start_time and assignment.applies_on(day - timedelta(days=1))
              and now <= timeutil.shift_end_utc(day - timedelta(days=1), shift.start_time, shift.end_time, location.timezone)):
            today.setdefault((shift.id, location.id), (shift, location))
    return [{"location_id": location.id, "location_name": location.name, "shift": shift.name, "start": f"{shift.start_time:%H:%M}",
             "end": f"{shift.end_time:%H:%M}", "week_off": shift.kind == "weekoff"}
            for shift, location in sorted(today.values(), key=lambda pair: pair[0].start_time)]


def incomplete_tasks(db: Session, user: User, record: AttendanceRecord) -> list[ChecklistInstance]:
    emp = user.employee
    unassigned = and_(ChecklistInstance.assigned_employee_id.is_(None),
                      ChecklistInstance.shift_key.in_((0, record.shift_id or 0)),
                      or_(ChecklistTask.assigned_role.is_(None), ChecklistTask.assigned_role.in_(role_names(user))))
    return db.scalars(
        select(ChecklistInstance).join(ChecklistTask, ChecklistTask.id == ChecklistInstance.task_id)
        .where(ChecklistInstance.location_id == record.location_id, ChecklistInstance.local_date == record.local_date,
               ChecklistTask.mandatory_for_checkout.is_(True), ChecklistInstance.status.not_in(DONE),
               or_(ChecklistInstance.assigned_employee_id == emp.id, unassigned))
    ).all()


def _recompute(record: AttendanceRecord, shift: Shift | None) -> None:
    if not record.check_out_at:
        return
    elapsed = int((record.check_out_at - record.check_in_at).total_seconds() // 60)
    break_minutes = shift.break_minutes if shift else 0
    payable = max(0, elapsed - break_minutes)
    record.payable_minutes = payable
    if shift:
        scheduled = timeutil.shift_minutes(shift.start_time, shift.end_time) - break_minutes
        limit = shift.overtime_after_minutes if shift.overtime_after_minutes is not None else scheduled
        record.overtime_minutes = max(0, payable - limit)
    else:
        record.overtime_minutes = 0


def _serialize(record: AttendanceRecord, now: datetime, names: dict[int, str] | None = None) -> dict:
    out = row(record, *FIELDS)
    out["open"] = record.open_flag == 1
    out["geo_flags"] = record.geo_flags
    out["snapshot_in"], out["snapshot_out"] = bool(record.check_in_snapshot), bool(record.check_out_snapshot)
    out["missed_checkout"] = (record.open_flag == 1 and
                              (now - record.check_in_at).total_seconds() > MISSED_CHECKOUT_HOURS * 3600)
    if names is not None:
        out["employee_name"] = names.get(record.employee_id)
    return out


class ChallengeIn(BaseModel):
    action: Literal["in", "out"]


@router.post("/face-challenge", status_code=201)
def face_challenge(body: ChallengeIn, user: User = Depends(require("attendance.self")), db: Session = Depends(get_db)):
    """A random sequence of head turns for the camera screen to show; none when live checks are off."""
    emp = _employee(user)
    if not _liveness_on(db):
        return {"required": False}
    now = timeutil.utc_now()
    recent = db.scalar(select(func.count()).select_from(FaceChallenge).where(FaceChallenge.employee_id == emp.id,
                                                                               FaceChallenge.created_at > now - timedelta(minutes=1)))
    if recent >= 10:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many camera checks started; wait a minute")
    db.execute(delete(FaceChallenge).where(FaceChallenge.created_at < now - timedelta(days=1)))
    steps = [secrets.choice(CHALLENGE_STEPS) for _ in range(CHALLENGE_LENGTH)]
    while len(set(steps)) < len(CHALLENGE_STEPS):  # always both directions, so a recording of one turn cannot pass
        steps = [secrets.choice(CHALLENGE_STEPS) for _ in range(CHALLENGE_LENGTH)]
    challenge = FaceChallenge(employee_id=emp.id, token=secrets.token_urlsafe(32), action=body.action, created_at=now, steps=steps)
    db.add(challenge)
    db.commit()
    return {"required": True, "token": challenge.token, "steps": challenge.steps, "expires_in": CHALLENGE_TTL_S}


@router.get("/{record_id}/snapshot/{which}")
def snapshot(record_id: int, which: Literal["in", "out"], user: User = Depends(require("attendance.view")), db: Session = Depends(get_db)):
    """The photo kept with a face check, only for people who may view attendance at that location; every view is audited."""
    record = db.get(AttendanceRecord, record_id)
    if not record:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Record not found")
    check_location(user, db, record.location_id)
    name = record.check_in_snapshot if which == "in" else record.check_out_snapshot
    path = Path(settings.upload_dir) / "faces" / name if name else None
    if path is None or not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No snapshot was kept")
    audit(db, user, "attendance.snapshot_view", "attendance_record", record.id, None, {"which": which})
    db.commit()
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, no-store"})


@router.post("/check-in", status_code=201)
def check_in(body: CheckInIn, user: User = Depends(require("attendance.self")), db: Session = Depends(get_db)):
    emp = _employee(user)
    if body.location_id is None:
        if get_setting(db, "attendance.by_location"):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Choose a location to check in at")
        location, away = _place_by_position(db, user, emp, body)
    else:
        check_location(user, db, body.location_id)
        location = db.get(Location, body.location_id)
        if not location.active:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Location is not active")
        away = _enforce_geofence(db, location, body, "check in")
    if _open_record(db, emp):
        raise HTTPException(status.HTTP_409_CONFLICT, "You are already checked in")
    photo = _snapshot_bytes(db, body) if get_setting(db, "attendance.face_required") else None
    face = _verify_face(db, emp, body, "check in")
    now = timeutil.utc_now()
    shift, day = _pick_shift(db, emp, location, now)
    late = 0
    if shift:
        minutes_after_start = int((now - timeutil.local_to_utc(day, shift.start_time, location.timezone))
                                  .total_seconds() // 60)
        late = minutes_after_start if minutes_after_start > shift.grace_minutes else 0
    record = AttendanceRecord(employee_id=emp.id, location_id=location.id, shift_id=shift.id if shift else None,
                              local_date=day, check_in_at=now, late_minutes=late, open_flag=1,
                              check_in_geo=_geo_evidence(db, emp, body, away, now), check_in_face=face,
                              check_in_snapshot=_write_snapshot(photo))
    try:
        db.add(record)
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "You are already checked in") from None
    db.commit()
    return _serialize(record, now)


@router.post("/check-out")
def check_out(body: CheckOutIn, user: User = Depends(require("attendance.self")), db: Session = Depends(get_db)):
    emp = _employee(user)
    record = _open_record(db, emp)
    if not record:
        raise HTTPException(status.HTTP_409_CONFLICT, "You are not checked in")
    away = _enforce_geofence(db, db.get(Location, record.location_id), body, "check out")
    pending = incomplete_tasks(db, user, record)
    reason = (body.exception_reason or "").strip()
    if pending and len(reason) < 5:
        raise HTTPException(status.HTTP_409_CONFLICT, detail={
            "message": "Mandatory tasks are incomplete; finish them or give an exception reason",
            "tasks": [{"id": t.id, "task_id": t.task_id} for t in pending]})
    photo = _snapshot_bytes(db, body) if get_setting(db, "attendance.face_required") else None
    face = _verify_face(db, emp, body, "check out")
    now = timeutil.utc_now()
    record.check_out_geo = _geo_evidence(db, emp, body, away, now)
    record.check_out_face = face
    record.check_out_snapshot = _write_snapshot(photo)
    record.check_out_at = now
    record.open_flag = None
    _recompute(record, db.get(Shift, record.shift_id) if record.shift_id else None)
    if pending:
        record.exception_reason = reason
        audit(db, user, "attendance.checkout_exception", "attendance_record", record.id, None,
              {"reason": reason, "incomplete_instance_ids": [t.id for t in pending]})
    db.commit()
    return _serialize(record, now)


@router.get("/me/schedule")
def my_schedule(month: str | None = None, user: User = Depends(require("attendance.self")), db: Session = Depends(get_db)):
    """The signed-in employee's rostered shifts, week offs and recorded leave for each day of a month (YYYY-MM, this month by default)."""
    emp = _employee(user)
    today = timeutil.local_date(timeutil.utc_now(), get_organization(db)["timezone"])
    try:
        first = date.fromisoformat(f"{month}-01") if month else today.replace(day=1)
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "month must be YYYY-MM") from None
    last = (first.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    rostered = db.execute(
        select(ShiftAssignment, Shift, Location).join(Shift, Shift.id == ShiftAssignment.shift_id)
        .join(Location, Location.id == ShiftAssignment.location_id)
        .where(ShiftAssignment.employee_id == emp.id, Shift.active.is_(True), Location.active.is_(True))).all()
    leave = {a.local_date: a.absence_type for a in db.scalars(select(AbsenceRecord).where(
        AbsenceRecord.employee_id == emp.id, AbsenceRecord.local_date >= first, AbsenceRecord.local_date <= last,
        AbsenceRecord.voided_at.is_(None)))}
    punches: dict[date, list[AttendanceRecord]] = {}
    for rec in db.scalars(select(AttendanceRecord).where(AttendanceRecord.employee_id == emp.id, AttendanceRecord.local_date >= first,
                                                         AttendanceRecord.local_date <= last).order_by(AttendanceRecord.check_in_at)):
        punches.setdefault(rec.local_date, []).append(rec)
    days = []
    for n in range((last - first).days + 1):
        day = first + timedelta(days=n)
        shifts = [{"name": shift.name, "start": f"{shift.start_time:%H:%M}", "end": f"{shift.end_time:%H:%M}",
                   "week_off": shift.kind == "weekoff", "location": location.name}
                  for assignment, shift, location in sorted(rostered, key=lambda r: r[1].start_time) if assignment.applies_on(day)]
        worked = [{"check_in_at": iso(r.check_in_at), "check_out_at": iso(r.check_out_at) if r.check_out_at else None,
                   "late_minutes": r.late_minutes, "open": r.open_flag == 1} for r in punches.get(day, [])]
        expected = any(not s["week_off"] for s in shifts) and not leave.get(day)
        # what happened: on a past day a rostered working day with no punch and no leave was missed
        outcome = ("on_duty" if any(w["open"] for w in worked) else "late" if any(w["late_minutes"] for w in worked) else "worked") if worked \
            else "missed" if expected and day < today else None
        days.append({"date": day.isoformat(), "shifts": shifts, "leave": leave.get(day), "worked": worked, "outcome": outcome})
    return {"month": first.strftime("%Y-%m"), "today": today.isoformat(), "days": days}


@router.get("/me/status")
def my_status(user: User = Depends(require("attendance.self")), db: Session = Depends(get_db)):
    emp = _employee(user)
    now = timeutil.utc_now()
    record = _open_record(db, emp)
    out = {"checked_in": record is not None, "server_time": iso(now), "employee": emp.full_name,
           "employee_code": emp.employee_code, "record": None, "incomplete_task_count": 0,
           "face_required": bool(get_setting(db, "attendance.face_required")), "face_enrolled": emp.face_descriptor is not None,
           "rostered_today": rostered_today(db, emp, now)}
    if record:
        out["record"] = _serialize(record, now)
        out["incomplete_task_count"] = len(incomplete_tasks(db, user, record))
        location = db.get(Location, record.location_id)
        out["location"] = {"id": location.id, "name": location.name, "timezone": location.timezone, "geofence": bool(location.geofence_radius_m)}
        if record.shift_id:
            out["shift"] = db.get(Shift, record.shift_id).name
    return out


@router.get("/mine")
def my_history(page: int = 1, size: int = 25, user: User = Depends(require("attendance.self")),
               db: Session = Depends(get_db)):
    emp = _employee(user)
    now = timeutil.utc_now()
    total, rows = paginate(db, select(AttendanceRecord).where(AttendanceRecord.employee_id == emp.id)
                           .order_by(AttendanceRecord.check_in_at.desc()), page, size)
    return {"total": total, "items": [_serialize(r[0], now) for r in rows]}


@router.get("")
def list_attendance(location_id: int | None = None, employee_id: int | None = None, date_from: date | None = None,
                    date_to: date | None = None, page: int = 1, size: int = 25,
                    user: User = Depends(require("attendance.view")), db: Session = Depends(get_db)):
    stmt = select(AttendanceRecord)
    allowed = scoped_locations(user, db)
    if location_id is not None:
        check_location(user, db, location_id)
        stmt = stmt.where(AttendanceRecord.location_id == location_id)
    elif allowed is not None:
        stmt = stmt.where(AttendanceRecord.location_id.in_(allowed))
    if employee_id is not None:
        stmt = stmt.where(AttendanceRecord.employee_id == employee_id)
    if date_from:
        stmt = stmt.where(AttendanceRecord.local_date >= date_from)
    if date_to:
        stmt = stmt.where(AttendanceRecord.local_date <= date_to)
    total, rows = paginate(db, stmt.order_by(AttendanceRecord.check_in_at.desc()), page, size)
    now = timeutil.utc_now()
    ids = {r[0].employee_id for r in rows}
    names = dict(db.execute(select(Employee.id, Employee.full_name).where(Employee.id.in_(ids))).all()) if ids else {}
    return {"total": total, "items": [_serialize(r[0], now, names) for r in rows]}


@router.post("/manual", status_code=201)
def add_manual(body: ManualIn, user: User = Depends(require("attendance.correct")), db: Session = Depends(get_db)):
    """A manager records the punch in and out an employee missed; it counts as a present day like any other."""
    emp = db.get(Employee, body.employee_id)
    if not emp or emp.status != "active":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Employee is not active at this location")
    location = employee_place(user, db, emp, body.location_id)
    now = timeutil.utc_now()
    today = timeutil.local_date(now, location.timezone)
    if not (today - timedelta(days=MANUAL_DAYS_BACK) <= body.day <= today):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"The date must be today or within the last {MANUAL_DAYS_BACK} days")
    check_in = timeutil.local_to_utc(body.day, body.check_in_time, location.timezone)
    check_out_day = body.day if body.check_out_time > body.check_in_time else body.day + timedelta(days=1)
    check_out = timeutil.local_to_utc(check_out_day, body.check_out_time, location.timezone)
    if body.check_out_time == body.check_in_time:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Check-out must be after check-in")
    if check_out > now:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The check-out time is in the future")
    if (check_out - check_in) > timedelta(hours=20):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A shift cannot be longer than 20 hours")
    if db.scalar(select(AttendanceRecord.id).where(AttendanceRecord.employee_id == emp.id, AttendanceRecord.local_date == body.day)):
        raise HTTPException(status.HTTP_409_CONFLICT, "There is already an attendance record that day; correct its times instead")
    if db.scalar(select(AbsenceRecord.id).where(AbsenceRecord.employee_id == emp.id, AbsenceRecord.local_date == body.day,
                                                AbsenceRecord.voided_at.is_(None))):
        raise HTTPException(status.HTTP_409_CONFLICT, "An absence or leave is recorded that day; cancel it first")
    shift, _ = _pick_shift(db, emp, location, check_in)
    late = 0
    if shift:
        after_start = int((check_in - timeutil.local_to_utc(body.day, shift.start_time, location.timezone)).total_seconds() // 60)
        late = after_start if after_start > shift.grace_minutes else 0
    reason = " ".join(body.reason.split())
    record = AttendanceRecord(employee_id=emp.id, location_id=location.id, shift_id=shift.id if shift else None, local_date=body.day,
                              check_in_at=check_in, check_out_at=check_out, late_minutes=late, open_flag=None,
                              exception_reason=f"{MANUAL_PREFIX}: {reason}", verified_by=user.id)
    db.add(record)
    db.flush()
    _recompute(record, shift)
    for field, value in (("check_in_at", check_in), ("check_out_at", check_out)):
        db.add(AttendanceCorrection(attendance_id=record.id, corrected_by=user.id, field=field, old_value=None,
                                    new_value=iso(value), reason=f"Manual entry: {reason}"))
    audit(db, user, "attendance.manual", "attendance_record", record.id, None,
          {"employee_id": emp.id, "date": body.day.isoformat(), "check_in": iso(check_in), "check_out": iso(check_out), "reason": reason})
    if emp.user_id:
        notify(db, [emp.user_id], "attendance_manual", f"Attendance added for {body.day.strftime('%d %b %Y')}",
               key=f"manual_att:{record.id}", body=f"Your manager recorded your attendance: {reason}", location_id=location.id,
               link="/attendance")
    db.commit()
    return _serialize(record, now)


@router.post("/{attendance_id}/correct")
def correct(attendance_id: int, body: CorrectionIn, user: User = Depends(require("attendance.correct")),
            db: Session = Depends(get_db)):
    record = db.get(AttendanceRecord, attendance_id)
    if not record:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attendance record not found")
    new_value = timeutil.aware_to_utc(body.new_value)
    old_value = getattr(record, body.field)
    check_in = new_value if body.field == "check_in_at" else record.check_in_at
    check_out = new_value if body.field == "check_out_at" else record.check_out_at
    if check_out and check_out <= check_in:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Check-out must be after check-in")
    db.add(AttendanceCorrection(attendance_id=record.id, corrected_by=user.id, field=body.field,
                                old_value=iso(old_value), new_value=iso(new_value), reason=body.reason))
    setattr(record, body.field, new_value)
    if body.field == "check_out_at":
        record.open_flag = None
    shift = db.get(Shift, record.shift_id) if record.shift_id else None
    _recompute(record, shift)
    audit(db, user, "attendance.correct", "attendance_record", record.id,
          {body.field: iso(old_value)}, {body.field: iso(new_value), "reason": body.reason})
    db.commit()
    return _serialize(record, timeutil.utc_now())


class RemoveIn(BaseModel):
    reason: str = Field(min_length=5, max_length=500)


@router.post("/{attendance_id}/remove")
def remove(attendance_id: int, body: RemoveIn, user: User = Depends(require("attendance.correct")), db: Session = Depends(get_db)):
    """Deletes a record entered in error; its values and the reason stay in the audit log."""
    record = db.get(AttendanceRecord, attendance_id)
    if not record:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attendance record not found")
    check_location(user, db, record.location_id)
    used = blockers(db, record, frozenset({"attendance_correction"}))
    if used:
        raise HTTPException(status.HTTP_409_CONFLICT, f"This record is used by {', '.join(used)}")
    before = {"employee_id": record.employee_id, "location_id": record.location_id, "date": record.local_date.isoformat(),
              "check_in": iso(record.check_in_at), "check_out": iso(record.check_out_at), "note": record.exception_reason}
    db.execute(delete(AttendanceCorrection).where(AttendanceCorrection.attendance_id == record.id))
    db.delete(record)
    audit(db, user, "attendance.delete", "attendance_record", attendance_id, before, {"reason": " ".join(body.reason.split())})
    db.commit()
    return {"deleted": attendance_id}


@router.post("/{attendance_id}/day-off")
def change_to_day_off(attendance_id: int, body: RemoveIn, user: User = Depends(require("attendance.correct")), db: Session = Depends(get_db)):
    """Replaces a punch record entered for a day the person was off with a day off, in one step; the punch stays in the audit log."""
    if "attendance.absence" not in permissions_of(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You may not record a day off")
    record = db.get(AttendanceRecord, attendance_id)
    if not record:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attendance record not found")
    check_location(user, db, record.location_id)
    today = timeutil.local_date(timeutil.utc_now(), db.get(Location, record.location_id).timezone)
    if record.local_date < today - timedelta(days=PAST_DAYS):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"A day off can be recorded only for the last {PAST_DAYS} days")
    used = blockers(db, record, frozenset({"attendance_correction"}))
    if used:
        raise HTTPException(status.HTTP_409_CONFLICT, f"This record is used by {', '.join(used)}")
    reason = " ".join(body.reason.split())
    before = {"employee_id": record.employee_id, "location_id": record.location_id, "date": record.local_date.isoformat(),
              "check_in": iso(record.check_in_at), "check_out": iso(record.check_out_at), "note": record.exception_reason}
    day = AbsenceRecord(employee_id=record.employee_id, location_id=record.location_id, local_date=record.local_date,
                        absence_type="day_off", note=reason, recorded_by=user.id)
    db.execute(delete(AttendanceCorrection).where(AttendanceCorrection.attendance_id == record.id))
    db.delete(record)
    db.flush()  # the punch goes first so the day is free for the day off
    db.add(day)
    db.flush()
    audit(db, user, "attendance.to_day_off", "absence_record", day.id, before, {"reason": reason})
    db.commit()
    return {"absence_id": day.id}
