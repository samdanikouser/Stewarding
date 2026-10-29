from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .. import timeutil
from ..audit import audit
from ..db import get_db
from ..deps import check_location, require, scoped_locations
from ..models import (ApprovalRecord, CorrectiveAction, Employee, Equipment, EquipmentSchedule, FoodItem, Location, Lot, Notification, ReadingLot,
                      TemperatureReading, User)
from ..pagination import paginate, row
from ..permissions import MANAGER, SUPERVISOR
from ..services.notify import notify, recipients
from ..services.scan import require_scan
from ..services.settings import get_setting
from ..services.traceability import usable
from ..services.monitoring import (CLOSED_ACTIONS, already_recorded, closed_until, describe, due_checks, failure_count, judge, pending_entries,
                                  resolve_alerts, resolve_chain)
from .equipment import serialize as serialize_equipment
from .uploads import is_valid_evidence

router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])

READING_FIELDS = ("id", "equipment_id", "schedule_id", "location_id", "recorded_at", "stage", "source", "parameter", "unit",
                  "value_type", "value", "reference", "min_limit", "max_limit", "passed", "recorded_by", "comment", "evidence_path", "retest_of_id",
                  "reviewed_by", "reviewed_at", "start_reading_id", "rejected_by", "rejected_at", "reject_reason")
ACTION_FIELDS = ("id", "reading_id", "action", "taken_by", "taken_at", "retest_due_at", "status", "resolved_at",
                 "escalated_at")


class ReadingIn(BaseModel):
    equipment_id: int
    schedule_id: int
    value: Decimal | None = Field(default=None, ge=-100000, le=100000)
    answer: str | None = Field(default=None, max_length=500)
    reference: str | None = Field(default=None, max_length=120)
    lot_ids: list[int] = Field(default_factory=list, max_length=20)
    comment: str | None = Field(default=None, max_length=1000)
    evidence_path: str | None = None
    corrective_action: str | None = Field(default=None, max_length=1000)
    retest_of_id: int | None = None
    start_reading_id: int | None = None


class ReviewManyIn(BaseModel):
    reading_ids: list[int] = Field(min_length=1, max_length=200)


class BatchItem(BaseModel):
    schedule_id: int
    value: Decimal | None = Field(default=None, ge=-100000, le=100000)
    answer: str | None = Field(default=None, max_length=500)
    reference: str | None = Field(default=None, max_length=120)
    lot_ids: list[int] = Field(default_factory=list, max_length=20)
    comment: str | None = Field(default=None, max_length=1000)
    evidence_path: str | None = None
    corrective_action: str | None = Field(default=None, max_length=1000)


class BatchIn(BaseModel):
    equipment_id: int
    start_reading_id: int | None = None
    readings: list[BatchItem] = Field(min_length=1, max_length=20)


class ActionIn(BaseModel):
    action: str = Field(min_length=5, max_length=1000)


class DecisionIn(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")
    note: str | None = Field(default=None, max_length=500)


def _equipment_for(db: Session, user: User, equipment_id: int) -> Equipment:
    eq = db.get(Equipment, equipment_id)
    if not eq:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Monitoring point not found")
    check_location(user, db, eq.location_id)
    return eq


def _visible_equipment(db: Session, user: User, location_id: int | None) -> list[Equipment]:
    stmt = select(Equipment).where(Equipment.active.is_(True))
    allowed = scoped_locations(user, db)
    if location_id is not None:
        check_location(user, db, location_id)
        stmt = stmt.where(Equipment.location_id == location_id)
    elif allowed is not None:
        stmt = stmt.where(Equipment.location_id.in_(allowed))
    return list(db.scalars(stmt.order_by(Equipment.location_id, Equipment.code)))


def _latest_action(db: Session, reading_id: int) -> CorrectiveAction | None:
    return db.scalar(select(CorrectiveAction).where(CorrectiveAction.reading_id == reading_id)
                     .order_by(CorrectiveAction.id.desc()))


def _latest_actions(db: Session, reading_ids: list[int]) -> dict[int, CorrectiveAction]:
    """The newest corrective action of each reading from one query, keyed by reading id."""
    if not reading_ids:
        return {}
    rows = db.scalars(select(CorrectiveAction).where(CorrectiveAction.reading_id.in_(reading_ids)).order_by(CorrectiveAction.id))
    return {action.reading_id: action for action in rows}


def _lots_of(db: Session, reading_ids: list[int]) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {i: [] for i in reading_ids}
    if reading_ids:
        for reading_id, lot_id, code, item, pack in db.execute(
                select(ReadingLot.reading_id, Lot.id, Lot.code, FoodItem.name, Lot.pack_description).join(Lot, Lot.id == ReadingLot.lot_id)
                .join(FoodItem, FoodItem.id == Lot.food_item_id).where(ReadingLot.reading_id.in_(reading_ids)).order_by(Lot.id)):
            out[reading_id].append({"id": lot_id, "code": code, "item": item, "pack": pack})
    return out


def _serialize_readings(db: Session, readings: list[TemperatureReading], names: dict[int, str]) -> list[dict]:
    actions = _latest_actions(db, [r.id for r in readings])
    lots = _lots_of(db, [r.id for r in readings])
    return [_serialize_reading(db, r, names, actions, lots[r.id]) for r in readings]


def _serialize_reading(db: Session, reading: TemperatureReading, names: dict[int, str],
                       actions: dict[int, CorrectiveAction] | None = None, lots: list[dict] | None = None) -> dict:
    out = row(reading, *READING_FIELDS)
    out["lots"] = lots if lots is not None else _lots_of(db, [reading.id])[reading.id]
    out["recorded_by_name"] = names.get(reading.recorded_by)
    out["reviewed_by_name"] = names.get(reading.reviewed_by)
    out["rejected_by_name"] = names.get(reading.rejected_by)
    out["display"] = describe(reading)
    action = actions.get(reading.id) if actions is not None else _latest_action(db, reading.id)
    out["corrective_action"] = row(action, *ACTION_FIELDS) if action else None
    return out


def _names(db: Session, user_ids: set[int]) -> dict[int, str]:
    if not user_ids:
        return {}
    rows = db.execute(select(Employee.user_id, Employee.full_name).where(Employee.user_id.in_(user_ids))).all()
    return dict(rows)


@router.get("/equipment")
def equipment_for_recording(location_id: int | None = None, user: User = Depends(require("temp.view")),
                            db: Session = Depends(get_db)):
    return [serialize_equipment(db, eq) for eq in _visible_equipment(db, user, location_id)]


@router.get("/due")
def due(location_id: int | None = None, user: User = Depends(require("temp.view")), db: Session = Depends(get_db)):
    return due_checks(db, _visible_equipment(db, user, location_id), timeutil.utc_now())


@router.get("/pending")
def pending(location_id: int | None = None, user: User = Depends(require("temp.view")), db: Session = Depends(get_db)):
    return pending_entries(db, _visible_equipment(db, user, location_id), timeutil.utc_now())


def _entry_started(db: Session, eq: Equipment, sched: EquipmentSchedule, start_reading_id: int | None) -> TemperatureReading | None:
    """The time-in reading a time-out closes; none for a check that is not a time out."""
    if sched.phase != "finish":
        return None
    start = db.get(TemperatureReading, start_reading_id) if start_reading_id else None
    if not start or start.rejected_at or start.equipment_id != eq.id or db.scalar(select(EquipmentSchedule.phase).where(EquipmentSchedule.id == start.schedule_id)) != "start":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Choose the entry this time out belongs to")
    if db.scalar(select(TemperatureReading.id).where(TemperatureReading.start_reading_id == start.id, TemperatureReading.schedule_id == sched.id)):
        raise HTTPException(status.HTTP_409_CONFLICT, "The time out is already recorded for this entry")
    return start


def _lots_used(db: Session, user: User, sched: EquipmentSchedule, body: ReadingIn, start: TemperatureReading | None) -> list[Lot]:
    """The food lots a check names: chosen on the form, or carried over from the time-in entry it closes."""
    if start is not None and not body.lot_ids:
        return list(db.scalars(select(Lot).join(ReadingLot, ReadingLot.lot_id == Lot.id).where(ReadingLot.reading_id == start.id).order_by(Lot.id)))
    if not body.lot_ids and body.retest_of_id is not None:
        return list(db.scalars(select(Lot).join(ReadingLot, ReadingLot.lot_id == Lot.id).where(ReadingLot.reading_id == body.retest_of_id).order_by(Lot.id)))
    if not body.lot_ids:
        if sched.trace_lots:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{sched.stage}: choose the food lot or lots this check is about")
        return []
    found = {lot.id: lot for lot in db.scalars(select(Lot).where(Lot.id.in_(set(body.lot_ids))))}
    missing = set(body.lot_ids) - set(found)
    if missing:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown food lot")
    now = timeutil.utc_now()
    for lot in found.values():
        check_location(user, db, lot.location_id)
        reason = usable(lot, now)
        if reason:
            raise HTTPException(status.HTTP_409_CONFLICT, f"{sched.stage}: {reason}")
    return [found[i] for i in dict.fromkeys(body.lot_ids)]


def _record(db: Session, user: User, body: ReadingIn) -> TemperatureReading:
    eq = _equipment_for(db, user, body.equipment_id)
    if not eq.active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This monitoring point is inactive")
    require_scan(db, user, "equipment", eq.id, "scan.monitoring_required", eq.name)
    sched = db.get(EquipmentSchedule, body.schedule_id)
    if not sched or sched.equipment_id != eq.id or not sched.active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown check for this monitoring point")
    if sched.value_type in ("signature", "image") and not is_valid_evidence(body.answer):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{sched.stage}: add the {sched.value_type}")
    opens = closed_until(db, eq, sched, timeutil.utc_now()) if body.retest_of_id is None else None
    if opens:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{sched.stage} opens at {timeutil.to_local(opens, db.get(Location, eq.location_id).timezone):%H:%M}")
    if body.retest_of_id is None and already_recorded(db, eq, sched, timeutil.utc_now()):
        raise HTTPException(status.HTTP_409_CONFLICT, f"{sched.stage} is already recorded for this time")
    if sched.value_type == "number" and sched.min_value is None and sched.max_value is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Limits are not configured for this check")
    try:
        value, answer, passed = judge(sched, body.value.quantize(Decimal("0.01")) if body.value is not None else None, body.answer)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{sched.stage}: {exc}") from None
    start = _entry_started(db, eq, sched, body.start_reading_id)
    lots = _lots_used(db, user, sched, body, start)
    reference = ", ".join(lot.code for lot in lots)[:120] if lots else (start.reference if start else (body.reference or "").strip() or None)
    if sched.require_reference and reference is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Enter the batch, lot or product reference for this check")
    if body.evidence_path and not is_valid_evidence(body.evidence_path):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown evidence file")

    original_action = None
    if body.retest_of_id is not None:
        original = db.get(TemperatureReading, body.retest_of_id)
        if not original or original.equipment_id != eq.id or original.schedule_id != sched.id or original.passed:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "A retest must refer to a failed reading of the same check")
        if original.rejected_at:
            raise HTTPException(status.HTTP_409_CONFLICT, "That reading was rejected; record the check again instead of retesting it")
        if db.scalar(select(TemperatureReading.id).where(TemperatureReading.retest_of_id == original.id, TemperatureReading.rejected_at.is_(None))):
            raise HTTPException(status.HTTP_409_CONFLICT, "This reading has already been retested")
        original_action = _latest_action(db, original.id)
        if not original_action or original_action.status != "retest_due":
            raise HTTPException(status.HTTP_409_CONFLICT, "Record the corrective action before retesting")

    now = timeutil.utc_now()
    reading = TemperatureReading(
        equipment_id=eq.id, schedule_id=sched.id, location_id=eq.location_id, recorded_at=now, stage=sched.stage,
        source=sched.source, parameter=sched.parameter, unit=sched.unit, value_type=sched.value_type, value=value,
        answer=answer, reference=reference, min_limit=sched.min_value, max_limit=sched.max_value, passed=passed,
        recorded_by=user.id, comment=body.comment, evidence_path=body.evidence_path, retest_of_id=body.retest_of_id,
        start_reading_id=start.id if start else None)
    db.add(reading)
    db.flush()
    db.add_all(ReadingLot(reading_id=reading.id, lot_id=lot.id) for lot in lots)

    if original_action and passed:
        resolve_chain(db, reading, now)
    elif original_action:
        original_action.status = "retest_failed"
    if not passed:
        _open_failure(db, user, eq, reading, body.corrective_action, now)
    return reading


@router.post("/readings", status_code=201)
def record_reading(body: ReadingIn, user: User = Depends(require("temp.record")), db: Session = Depends(get_db)):
    reading = _record(db, user, body)
    db.commit()
    return _serialize_reading(db, reading, _names(db, {reading.recorded_by}))


def _require_whole_cycle(db: Session, user: User, body: "BatchIn") -> None:
    """Every required question of the form being filled in must be answered or already recorded for this time; optional ones may be left out."""
    eq = _equipment_for(db, user, body.equipment_id)
    sent = {r.schedule_id for r in body.readings}
    active = list(db.scalars(select(EquipmentSchedule).where(EquipmentSchedule.equipment_id == eq.id, EquipmentSchedule.active.is_(True))))
    now = timeutil.utc_now()

    def when(s: EquipmentSchedule) -> tuple:
        return (s.timing, s.time_of_day, s.interval_minutes, s.weekdays, s.day_of_month, s.phase)

    groups = {when(s) for s in active if s.id in sent}
    missing = [s.stage for s in active if when(s) in groups and s.required and s.id not in sent and not already_recorded(db, eq, s, now)]
    if missing:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Answer the required questions: {', '.join(missing)}")


@router.post("/readings/batch", status_code=201)
def record_readings(body: BatchIn, user: User = Depends(require("temp.record")), db: Session = Depends(get_db)):
    """Saves every measurement of one cycle (for example wash and rinse) together, or none of them."""
    if len({r.schedule_id for r in body.readings}) != len(body.readings):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A check appears twice")
    _require_whole_cycle(db, user, body)
    readings = [_record(db, user, ReadingIn(equipment_id=body.equipment_id, start_reading_id=body.start_reading_id, **r.model_dump())) for r in body.readings]
    db.commit()
    names = _names(db, {user.id})
    return _serialize_readings(db, readings, names)


def _open_failure(db: Session, user: User, eq: Equipment, reading: TemperatureReading, text: str | None,
                  now: datetime) -> None:
    has_text = bool(text and len(text.strip()) >= 5)
    db.add(CorrectiveAction(
        reading_id=reading.id, action=text.strip() if has_text else "", taken_by=user.id,
        status="retest_due" if has_text else "action_required",
        retest_due_at=now + timedelta(minutes=get_setting(db, "temp.retest_minutes")) if has_text else None))
    answered = {"yes_no": "Answered No", "choice": f"Answered {reading.answer}"}
    limits = answered[reading.value_type] if reading.value_type in answered else f"Limits {reading.min_limit or '-'} to {reading.max_limit or '-'} {reading.unit or ''}".strip()
    notify(db, recipients(db, eq.location_id, SUPERVISOR, MANAGER), "monitoring_failed",
           f"Failed check: {eq.name} ({reading.stage}) {describe(reading)}",
           key=f"temp_fail:{reading.id}", body=f"{limits}. Corrective action and retest required.",
           priority="critical", location_id=eq.location_id, link="/monitoring", requires_ack=True)
    if failure_count(db, eq.id, now) >= get_setting(db, "temp.repeat_failure_count"):
        notify(db, recipients(db, eq.location_id, MANAGER, SUPERVISOR), "equipment_maintenance",
               f"Repeated failures: {eq.name} needs review",
               key=f"maint:{eq.id}:{now.date().isoformat()}", priority="high", location_id=eq.location_id,
               link="/settings/monitoring", requires_ack=True)


@router.get("/readings")
def list_readings(equipment_id: int | None = None, location_id: int | None = None, date_from: date | None = None,
                  date_to: date | None = None, passed: bool | None = None, page: int = 1, size: int = 25,
                  user: User = Depends(require("temp.view")), db: Session = Depends(get_db)):
    stmt = select(TemperatureReading)
    allowed = scoped_locations(user, db)
    if location_id is not None:
        check_location(user, db, location_id)
        stmt = stmt.where(TemperatureReading.location_id == location_id)
    elif allowed is not None:
        stmt = stmt.where(TemperatureReading.location_id.in_(allowed))
    if equipment_id is not None:
        stmt = stmt.where(TemperatureReading.equipment_id == equipment_id)
    if passed is not None:
        stmt = stmt.where(TemperatureReading.passed.is_(passed))
    if date_from:
        stmt = stmt.where(TemperatureReading.recorded_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        stmt = stmt.where(TemperatureReading.recorded_at < datetime.combine(date_to + timedelta(days=1),
                                                                            datetime.min.time()))
    total, rows = paginate(db, stmt.order_by(TemperatureReading.recorded_at.desc()), page, size)
    readings = [r[0] for r in rows]
    names = _names(db, {r.recorded_by for r in readings} | {r.reviewed_by for r in readings if r.reviewed_by} | {r.rejected_by for r in readings if r.rejected_by})
    return {"total": total, "items": _serialize_readings(db, readings, names)}


@router.post("/readings/review")
def review_readings(body: ReviewManyIn, user: User = Depends(require("temp.review")), db: Session = Depends(get_db)):
    """Approves the chosen readings; whoever gets there first approves, and a reading already approved or recorded by you is skipped."""
    now, reviewed = timeutil.utc_now(), []
    for reading in db.scalars(select(TemperatureReading).where(TemperatureReading.id.in_(set(body.reading_ids)))):
        check_location(user, db, reading.location_id)
        if reading.reviewed_at or reading.rejected_at or reading.recorded_by == user.id:
            continue
        reading.reviewed_by, reading.reviewed_at = user.id, now
        reviewed.append(reading.id)
    audit(db, user, "monitoring.review_many", "temperature_reading", None, None, {"reading_ids": sorted(reviewed)})
    db.commit()
    return {"reviewed": len(reviewed), "skipped": len(set(body.reading_ids)) - len(reviewed)}


@router.post("/readings/{reading_id}/review")
def review_reading(reading_id: int, user: User = Depends(require("temp.review")), db: Session = Depends(get_db)):
    reading = db.get(TemperatureReading, reading_id)
    if not reading:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Reading not found")
    check_location(user, db, reading.location_id)
    if reading.recorded_by == user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You cannot review your own reading")
    if reading.reviewed_at or reading.rejected_at:
        raise HTTPException(status.HTTP_409_CONFLICT, "Reading was already reviewed")
    reading.reviewed_by, reading.reviewed_at = user.id, timeutil.utc_now()
    audit(db, user, "monitoring.review", "temperature_reading", reading.id)
    db.commit()
    return _serialize_reading(db, reading, _names(db, {reading.recorded_by}))


def _has_open_time_out(db: Session, reading: TemperatureReading) -> bool:
    """A time in cannot be rejected while a time out recorded against it still stands."""
    return db.scalar(select(TemperatureReading.id).where(TemperatureReading.start_reading_id == reading.id,
                                                         TemperatureReading.rejected_at.is_(None))) is not None


def _undo_effects(db: Session, reading: TemperatureReading, now: datetime) -> None:
    """A rejected reading no longer counts: its own failure is closed, and a retest it decided is reopened."""
    for action in db.scalars(select(CorrectiveAction).where(CorrectiveAction.reading_id == reading.id,
                                                            CorrectiveAction.status.not_in(CLOSED_ACTIONS))):
        action.status, action.resolved_at = "voided", now
    resolve_alerts(db, reading.id, now)
    if reading.retest_of_id is None:
        return
    reopen_at = now + timedelta(minutes=get_setting(db, "temp.retest_minutes"))
    previous_id = reading.retest_of_id
    while previous_id:
        for action in db.scalars(select(CorrectiveAction).where(CorrectiveAction.reading_id == previous_id)):
            closed_by_it = action.status == "resolved" and action.resolved_at is not None and action.resolved_at >= reading.recorded_at
            if closed_by_it or action.status == "retest_failed":
                action.status, action.resolved_at, action.retest_due_at = "retest_due", None, reopen_at
                db.execute(update(Notification).where(Notification.dedupe_key == f"temp_fail:{previous_id}").values(resolved_at=None))
        previous_id = db.scalar(select(TemperatureReading.retest_of_id).where(TemperatureReading.id == previous_id))


class RejectManyIn(ReviewManyIn):
    reason: str = Field(min_length=5, max_length=300)


@router.post("/readings/reject")
def reject_readings(body: RejectManyIn, user: User = Depends(require("temp.review")), db: Session = Depends(get_db)):
    """Rejects the chosen readings with one reason so they are recorded again; reviewed readings and your own are skipped."""
    now, rejected = timeutil.utc_now(), []
    for reading in db.scalars(select(TemperatureReading).where(TemperatureReading.id.in_(set(body.reading_ids)))):
        check_location(user, db, reading.location_id)
        if reading.reviewed_at or reading.rejected_at or reading.recorded_by == user.id or _has_open_time_out(db, reading):
            continue
        reading.rejected_by, reading.rejected_at, reading.reject_reason = user.id, now, body.reason.strip()
        _undo_effects(db, reading, now)
        rejected.append(reading)
        notify(db, [reading.recorded_by], "monitoring_rejected", f"Record again: {reading.stage}",
               key=f"reject_reading:{reading.id}", body=body.reason.strip(), priority="high", location_id=reading.location_id, link="/monitoring")
    audit(db, user, "monitoring.reject_many", "temperature_reading", None, None, {"reading_ids": sorted(r.id for r in rejected), "reason": body.reason.strip()})
    db.commit()
    return {"rejected": len(rejected), "skipped": len(set(body.reading_ids)) - len(rejected)}


@router.get("/corrective-actions")
def list_actions(action_status: str | None = Query(None, alias="status"), location_id: int | None = None,
                 user: User = Depends(require("temp.view")), db: Session = Depends(get_db)):
    stmt = select(CorrectiveAction, TemperatureReading).join(
        TemperatureReading, TemperatureReading.id == CorrectiveAction.reading_id)
    allowed = scoped_locations(user, db)
    if location_id is not None:
        check_location(user, db, location_id)
        stmt = stmt.where(TemperatureReading.location_id == location_id)
    elif allowed is not None:
        stmt = stmt.where(TemperatureReading.location_id.in_(allowed))
    stmt = stmt.where(CorrectiveAction.status.not_in(CLOSED_ACTIONS if action_status is None else ()))
    if action_status:
        stmt = stmt.where(CorrectiveAction.status == action_status)
    items = db.execute(stmt.order_by(CorrectiveAction.id.desc()).limit(200)).all()
    return [{**row(a, *ACTION_FIELDS), "equipment_id": r.equipment_id, "stage": r.stage, "display": describe(r),
             "recorded_at": row(r, "recorded_at")["recorded_at"], "location_id": r.location_id} for a, r in items]


def _action_for(db: Session, user: User, action_id: int) -> tuple[CorrectiveAction, TemperatureReading]:
    action = db.get(CorrectiveAction, action_id)
    if not action:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Corrective action not found")
    reading = db.get(TemperatureReading, action.reading_id)
    check_location(user, db, reading.location_id)
    return action, reading


@router.post("/corrective-actions/{action_id}/action")
def record_action(action_id: int, body: ActionIn, user: User = Depends(require("temp.record")),
                  db: Session = Depends(get_db)):
    action, _ = _action_for(db, user, action_id)
    if action.status != "action_required":
        raise HTTPException(status.HTTP_409_CONFLICT, f"Action is {action.status}")
    now = timeutil.utc_now()
    action.action, action.taken_by, action.taken_at = body.action.strip(), user.id, now
    action.status = "retest_due"
    action.retest_due_at = now + timedelta(minutes=get_setting(db, "temp.retest_minutes"))
    db.commit()
    return row(action, *ACTION_FIELDS)


@router.post("/corrective-actions/{action_id}/decision")
def decide(action_id: int, body: DecisionIn, user: User = Depends(require("temp.review")),
           db: Session = Depends(get_db)):
    action, reading = _action_for(db, user, action_id)
    if action.taken_by == user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You cannot approve your own corrective action")
    if action.status == "resolved":
        raise HTTPException(status.HTTP_409_CONFLICT, "Action is already resolved")
    now = timeutil.utc_now()
    if body.decision == "approve":
        action.status, action.resolved_at = "resolved", now
        resolve_alerts(db, reading.id, now)
    else:
        if not (body.note and body.note.strip()):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "A note is required when rejecting")
        action.status, action.retest_due_at = "action_required", None
        notify(db, [action.taken_by], "corrective_action_rejected", "Corrective action rejected - redo",
               key=f"reject_action:{action.id}:{now.isoformat()}", body=body.note, priority="high",
               location_id=reading.location_id, link="/monitoring")
    db.add(ApprovalRecord(subject_type="corrective_action", subject_id=action.id, decision=body.decision,
                          decided_by=user.id, reason=body.note))
    audit(db, user, f"monitoring.action_{body.decision}", "corrective_action", action.id, None, {"note": body.note})
    db.commit()
    return row(action, *ACTION_FIELDS)
