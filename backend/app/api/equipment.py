from datetime import time
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import audit
from ..db import get_db
from ..deps import check_location, require, scoped_locations
from ..models import Employee, Equipment, EquipmentSchedule, Location, Shift, TemperatureReading, User
from ..pagination import row
from ..services.settings import get_setting
from ..services.monitoring import failure_count
from ..services.monitoring_templates import BY_KEY, TEMPLATES
from .. import timeutil

router = APIRouter(prefix="/api/equipment", tags=["monitoring points"])

EQUIPMENT_FIELDS = ("id", "code", "name", "kind", "location_id", "manufacturer", "model", "serial_number",
                    "supervisor_id", "status", "procedure_reference", "maintenance_notes", "active")
SCHEDULE_FIELDS = ("id", "equipment_id", "stage", "parameter", "unit", "value_type", "require_reference", "source", "timing",
                   "time_of_day", "interval_minutes", "weekdays", "day_of_month", "shift_id", "min_value", "max_value", "options",
                   "fail_options", "max_length", "required", "reference_label", "phase", "trace_lots", "active")


class EquipmentIn(BaseModel):
    code: str = Field(min_length=2, max_length=30)
    name: str = Field(min_length=2, max_length=120)
    kind: str = Field(min_length=2, max_length=40)
    location_id: int
    manufacturer: str | None = None
    model: str | None = None
    serial_number: str | None = None
    supervisor_id: int | None = None
    status: str = Field(default="operational", pattern="^(operational|attention|out_of_service)$")
    procedure_reference: str | None = Field(default=None, max_length=300)
    maintenance_notes: str | None = None


class EquipmentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    manufacturer: str | None = None
    model: str | None = None
    serial_number: str | None = None
    supervisor_id: int | None = None
    status: str | None = Field(default=None, pattern="^(operational|attention|out_of_service)$")
    procedure_reference: str | None = Field(default=None, max_length=300)
    maintenance_notes: str | None = None
    active: bool | None = None


class ScheduleIn(BaseModel):
    stage: str = Field(min_length=2, max_length=60)
    parameter: str = Field(default="Temperature", min_length=2, max_length=60)
    unit: str | None = Field(default="°C", max_length=20)
    value_type: str = Field(default="number", pattern="^(number|yes_no|text|choice|date|time|signature|image)$")
    required: bool = True
    options: list[str] | None = None
    fail_options: list[str] | None = None
    max_length: int | None = Field(default=None, ge=1, le=500)
    require_reference: bool = False
    trace_lots: bool = False
    reference_label: str | None = Field(default=None, max_length=40)
    phase: Literal["start", "finish"] | None = None
    source: str = Field(default="machine_display", pattern="^(machine_display|independent_probe)$")
    timing: str = Field(pattern="^(startup|interval|checkpoint|manual)$")
    time_of_day: time | None = None
    interval_minutes: int | None = Field(default=None, gt=0, le=1440)
    weekdays: list[int] | None = None
    day_of_month: int | None = Field(default=None, ge=1, le=31)
    shift_id: int | None = None
    min_value: Decimal | None = Field(default=None, ge=-100000, le=100000)
    max_value: Decimal | None = Field(default=None, ge=-100000, le=100000)
    active: bool = True

    @model_validator(mode="after")
    def _check(self):
        if self.value_type != "number":
            self.min_value = self.max_value = self.unit = None
        if self.value_type != "choice":
            self.options = self.fail_options = None
        if self.value_type != "text":
            self.max_length = None
        if self.value_type == "text":
            self.max_length = self.max_length or 200
        if self.value_type == "choice":
            options = list(dict.fromkeys(" ".join(o.split()) for o in (self.options or []) if o.strip()))
            if not 2 <= len(options) <= 20 or any(len(o) > 80 for o in options):
                raise ValueError("Give between 2 and 20 answers to choose from, each up to 80 characters")
            fails = [" ".join(o.split()) for o in (self.fail_options or [])]
            if any(f not in options for f in fails):
                raise ValueError("A failing answer must be one of the listed answers")
            self.options, self.fail_options = options, list(dict.fromkeys(fails))
        if self.value_type == "number" and self.min_value is None and self.max_value is None:
            raise ValueError("A number field needs a minimum or a maximum; use Short text for anything without limits")
        if None not in (self.min_value, self.max_value) and self.min_value > self.max_value:
            raise ValueError("Minimum limit cannot exceed the maximum limit")
        if self.timing == "interval" and not self.interval_minutes:
            raise ValueError("Interval monitoring needs interval_minutes")
        if self.weekdays is not None and any(d < 0 or d > 6 for d in self.weekdays):
            raise ValueError("Weekdays must be 0 (Monday) to 6 (Sunday)")
        return self


def _schedule_values(body: ScheduleIn) -> dict:
    values = body.model_dump(exclude={"phase", "reference_label", "active"} - body.model_fields_set)
    values["weekdays"] = ",".join(str(d) for d in sorted(set(body.weekdays))) if body.weekdays else None
    return values


def schedule_out(s: EquipmentSchedule) -> dict:
    out = row(s, *SCHEDULE_FIELDS)
    out["weekdays"] = [int(d) for d in s.weekdays.split(",")] if s.weekdays else []
    return out


def _get(db: Session, user: User, equipment_id: int) -> Equipment:
    eq = db.get(Equipment, equipment_id)
    if not eq:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Monitoring point not found")
    check_location(user, db, eq.location_id)
    return eq


def serialize(db: Session, eq: Equipment) -> dict:
    schedules = db.scalars(select(EquipmentSchedule).where(EquipmentSchedule.equipment_id == eq.id)
                           .order_by(EquipmentSchedule.id))
    failures = failure_count(db, eq.id, timeutil.utc_now())
    return {**row(eq, *EQUIPMENT_FIELDS), "schedules": [schedule_out(s) for s in schedules],
            "recent_failures": failures,
            "needs_attention": eq.status != "operational" or failures >= get_setting(db, "temp.repeat_failure_count")}


def _validate_refs(db: Session, supervisor_id: int | None, shift_id: int | None = None) -> None:
    if supervisor_id is not None and not db.get(Employee, supervisor_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown supervisor")
    if shift_id is not None and not db.get(Shift, shift_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown shift")


@router.get("")
def list_equipment(location_id: int | None = None, kind: str | None = None,
                   user: User = Depends(require("equipment.view")), db: Session = Depends(get_db)):
    stmt = select(Equipment)
    allowed = scoped_locations(user, db)
    if location_id is not None:
        check_location(user, db, location_id)
        stmt = stmt.where(Equipment.location_id == location_id)
    elif allowed is not None:
        stmt = stmt.where(Equipment.location_id.in_(allowed))
    if kind:
        stmt = stmt.where(Equipment.kind == kind)
    return [serialize(db, eq) for eq in db.scalars(stmt.order_by(Equipment.location_id, Equipment.code))]


@router.post("", status_code=201)
def create_equipment(body: EquipmentIn, user: User = Depends(require("equipment.manage")),
                     db: Session = Depends(get_db)):
    check_location(user, db, body.location_id)
    _validate_refs(db, body.supervisor_id)
    if db.scalar(select(Equipment.id).where(Equipment.code == body.code)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Monitoring point code already exists")
    eq = Equipment(**body.model_dump())
    db.add(eq)
    db.flush()
    audit(db, user, "equipment.create", "equipment", eq.id, None, body.model_dump())
    db.commit()
    return serialize(db, eq)


@router.put("/{equipment_id}")
def update_equipment(equipment_id: int, body: EquipmentUpdate, user: User = Depends(require("equipment.manage")),
                     db: Session = Depends(get_db)):
    eq = _get(db, user, equipment_id)
    data = body.model_dump(exclude_unset=True)
    _validate_refs(db, data.get("supervisor_id"))
    before = {k: getattr(eq, k) for k in data}
    for key, value in data.items():
        setattr(eq, key, value)
    audit(db, user, "equipment.update", "equipment", eq.id, before, data)
    db.commit()
    return serialize(db, eq)


def _schedule_snapshot(s: EquipmentSchedule) -> dict:
    return {k: str(v) if v is not None else None for k, v in schedule_out(s).items()}


@router.post("/{equipment_id}/schedules", status_code=201)
def create_schedule(equipment_id: int, body: ScheduleIn, user: User = Depends(require("equipment.manage")),
                    db: Session = Depends(get_db)):
    eq = _get(db, user, equipment_id)
    _validate_refs(db, None, body.shift_id)
    sched = EquipmentSchedule(equipment_id=eq.id, **_schedule_values(body))
    db.add(sched)
    db.flush()
    audit(db, user, "equipment.schedule_create", "equipment_schedule", sched.id, None, _schedule_snapshot(sched))
    db.commit()
    return schedule_out(sched)


@router.put("/schedules/{schedule_id}")
def update_schedule(schedule_id: int, body: ScheduleIn, user: User = Depends(require("equipment.manage")),
                    db: Session = Depends(get_db)):
    sched = db.get(EquipmentSchedule, schedule_id)
    if not sched:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Schedule not found")
    _get(db, user, sched.equipment_id)
    _validate_refs(db, None, body.shift_id)
    before = _schedule_snapshot(sched)
    for key, value in _schedule_values(body).items():
        setattr(sched, key, value)
    audit(db, user, "equipment.schedule_update", "equipment_schedule", sched.id, before, _schedule_snapshot(sched))
    db.commit()
    return schedule_out(sched)


class ActiveIn(BaseModel):
    active: bool


@router.put("/schedules/{schedule_id}/active")
def set_schedule_active(schedule_id: int, body: ActiveIn, user: User = Depends(require("equipment.manage")),
                        db: Session = Depends(get_db)):
    sched = db.get(EquipmentSchedule, schedule_id)
    if not sched:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Schedule not found")
    _get(db, user, sched.equipment_id)
    before = sched.active
    sched.active = body.active
    audit(db, user, "equipment.schedule_active", "equipment_schedule", sched.id, {"active": before}, {"active": body.active})
    db.commit()
    return schedule_out(sched)


@router.delete("/schedules/{schedule_id}")
def delete_schedule(schedule_id: int, user: User = Depends(require("equipment.manage")), db: Session = Depends(get_db)):
    sched = db.get(EquipmentSchedule, schedule_id)
    if not sched:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Schedule not found")
    _get(db, user, sched.equipment_id)
    if db.scalar(select(TemperatureReading.id).where(TemperatureReading.schedule_id == sched.id).limit(1)):
        raise HTTPException(status.HTTP_409_CONFLICT, "This check has recorded readings; make it inactive instead")
    audit(db, user, "equipment.schedule_delete", "equipment_schedule", sched.id, _schedule_snapshot(sched), None)
    db.delete(sched)
    db.commit()
    return {"deleted": schedule_id}


@router.delete("/{equipment_id}")
def delete_equipment(equipment_id: int, user: User = Depends(require("equipment.manage")), db: Session = Depends(get_db)):
    eq = _get(db, user, equipment_id)
    if db.scalar(select(TemperatureReading.id).where(TemperatureReading.equipment_id == eq.id).limit(1)):
        raise HTTPException(status.HTTP_409_CONFLICT, "This monitoring point has recorded readings; make it inactive instead")
    audit(db, user, "equipment.delete", "equipment", eq.id, {k: getattr(eq, k) for k in EQUIPMENT_FIELDS}, None)
    for sched in db.scalars(select(EquipmentSchedule).where(EquipmentSchedule.equipment_id == eq.id)):
        db.delete(sched)
    db.delete(eq)
    db.commit()
    return {"deleted": equipment_id}


class FromTemplateIn(BaseModel):
    template: str
    location_id: int
    name: str | None = Field(default=None, min_length=2, max_length=120)
    supervisor_id: int | None = None


def _next_code(db: Session, prefix: str, location_code: str) -> str:
    n = 1
    while db.scalar(select(Equipment.id).where(Equipment.code == f"{prefix}-{location_code}-{n}")):
        n += 1
    return f"{prefix}-{location_code}-{n}"


@router.get("/templates")
def list_templates(user: User = Depends(require("equipment.manage"))):
    return [{"key": t["key"], "name": t["name"], "type": t["type"], "checks": [
        {"stage": c["stage"], "parameter": c["parameter"], "unit": c["unit"], "value_type": c["value_type"],
         "min_value": c.get("min_value"), "max_value": c.get("max_value"), "timing": c["timing"], "phase": c.get("phase")}
        for c in t["checks"]]}
        for t in TEMPLATES]


@router.post("/from-template", status_code=201)
def create_from_template(body: FromTemplateIn, user: User = Depends(require("equipment.manage")),
                         db: Session = Depends(get_db)):
    preset = BY_KEY.get(body.template)
    if not preset:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown template")
    check_location(user, db, body.location_id)
    _validate_refs(db, body.supervisor_id)
    location = db.get(Location, body.location_id)
    eq = Equipment(code=_next_code(db, preset["prefix"], location.code), name=body.name or f"{location.name} {preset['name']}",
                   kind=preset["type"], location_id=location.id, supervisor_id=body.supervisor_id)
    db.add(eq)
    db.flush()
    for check in preset["checks"]:
        weekdays = check.get("weekdays")
        db.add(EquipmentSchedule(equipment_id=eq.id, **{**check, "weekdays": weekdays}))
    audit(db, user, "equipment.create", "equipment", eq.id, None, {"template": body.template, "code": eq.code})
    db.commit()
    return serialize(db, eq)


class FieldIn(BaseModel):
    title: str = Field(min_length=2, max_length=60)
    value_type: str = Field(pattern="^(number|yes_no|text|choice|date|time|signature|image)$")
    required: bool = True
    unit: str | None = Field(default=None, max_length=20)
    min_value: Decimal | None = Field(default=None, ge=-100000, le=100000)
    max_value: Decimal | None = Field(default=None, ge=-100000, le=100000)
    options: list[str] | None = None
    fail_options: list[str] | None = None
    max_length: int | None = Field(default=None, ge=1, le=500)
    require_reference: bool = False
    trace_lots: bool = False


class FrequencyIn(BaseModel):
    mode: Literal["daily", "weekly", "monthly", "interval", "on_demand"]
    times: list[time] = Field(default_factory=list, max_length=6)
    weekdays: list[int] | None = None
    day_of_month: int | None = Field(default=None, ge=1, le=31)
    interval_minutes: int | None = Field(default=None, ge=5, le=1440)
    start: time | None = None

    @model_validator(mode="after")
    def _by_mode(self):
        if self.mode == "interval":
            if not self.interval_minutes or self.start is None:
                raise ValueError("Say how many minutes apart the checks are and when the first one is")
        elif self.mode != "on_demand" and (not self.times or len(set(self.times)) != len(self.times)):
            raise ValueError("Give at least one time, each different")
        if self.mode == "weekly" and not self.weekdays:
            raise ValueError("Choose the days of the week")
        if self.mode == "monthly" and not self.day_of_month:
            raise ValueError("Choose the day of the month")
        return self


class FormIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    kind: str = Field(default="Other", min_length=2, max_length=40)
    location_ids: list[int] = Field(min_length=1, max_length=20)
    fields: list[FieldIn] = Field(min_length=1, max_length=20)
    frequency: FrequencyIn
    supervisor_id: int | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, value):
        value = " ".join(value.split())
        if len(value) < 2:
            raise ValueError("Give the form a name")
        return value

    @model_validator(mode="after")
    def _titles(self):
        titles = [" ".join(f.title.split()).lower() for f in self.fields]
        if len(set(titles)) != len(titles):
            raise ValueError("Two fields have the same title")
        return self


def _schedules_for(form: FormIn) -> list[dict]:
    """One check per field per time; checks that share a time are recorded together as a single form."""
    freq = form.frequency
    slots = [{"timing": "manual", "time_of_day": None, "interval_minutes": None}] if freq.mode == "on_demand" else [{"timing": "interval", "interval_minutes": freq.interval_minutes, "time_of_day": freq.start}] if freq.mode == "interval" \
        else [{"timing": "checkpoint", "time_of_day": t, "interval_minutes": None} for t in sorted(freq.times)]
    out = []
    for slot in slots:
        for f in form.fields:
            title = " ".join(f.title.split())
            check = ScheduleIn(stage=title, parameter=title, unit=f.unit, value_type=f.value_type, require_reference=f.require_reference, trace_lots=f.trace_lots,
                               source="machine_display", weekdays=freq.weekdays if freq.mode == "weekly" else None,
                               day_of_month=freq.day_of_month if freq.mode == "monthly" else None, min_value=f.min_value,
                               max_value=f.max_value, options=f.options, fail_options=f.fail_options, max_length=f.max_length, required=f.required, **slot)
            out.append(_schedule_values(check))
    return out


@router.post("/forms", status_code=201)
def create_form(body: FormIn, user: User = Depends(require("equipment.manage")), db: Session = Depends(get_db)):
    """Creates a log form, which is a monitoring point with a check per field, at each chosen location."""
    _validate_refs(db, body.supervisor_id)
    locations = []
    for location_id in dict.fromkeys(body.location_ids):
        check_location(user, db, location_id)
        location = db.get(Location, location_id)
        if not location or not location.active:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown or inactive location")
        locations.append(location)
    try:
        schedules = _schedules_for(body)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    made = []
    for location in locations:
        eq = Equipment(code=_next_code(db, "FM", location.code), name=body.name, kind=body.kind, location_id=location.id,
                       supervisor_id=body.supervisor_id)
        db.add(eq)
        db.flush()
        db.add_all(EquipmentSchedule(equipment_id=eq.id, **values) for values in schedules)
        audit(db, user, "equipment.create", "equipment", eq.id, None, {"form": body.name, "code": eq.code, "fields": len(body.fields)})
        made.append(eq)
    db.commit()
    return {"points": [serialize(db, eq) for eq in made]}
