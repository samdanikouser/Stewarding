from bisect import bisect_left
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from .. import timeutil
from ..models import (CorrectiveAction, Equipment, EquipmentSchedule, Location, Notification, Shift,
                      TemperatureReading)
from .checklists import is_closed
from .reference import locations_by_id, shifts_by_id
from .settings import get_setting

DEFAULT_START = time(6, 0)
CLOSED_ACTIONS = ("resolved", "voided")  # a voided action belonged to a reading that was rejected


def evaluate(value: Decimal, minimum: Decimal | None, maximum: Decimal | None) -> bool:
    return (minimum is None or value >= minimum) and (maximum is None or value <= maximum)


def describe(reading) -> str:
    """A reading as people say it: the written or chosen answer, 'Yes' or 'No', or the number with its unit."""
    if reading.value_type in ("text", "choice", "date", "time", "signature", "image"):
        return reading.answer or ""
    if reading.value_type == "yes_no":
        return "Yes" if reading.value == 1 else "No"
    value = f"{reading.value.normalize():f}"
    return f"{value} {reading.unit}".strip() if reading.unit else value


def judge(sched, value, answer) -> tuple[Decimal | None, str | None, bool]:
    """Checks an answer against the field's rules and returns the value to store, the answer to store and whether it passed.

    Raises ValueError with a message for the person when the answer is not acceptable.
    """
    if sched.value_type == "number":
        if value is None:
            raise ValueError("Enter a number")
        return value, None, evaluate(value, sched.min_value, sched.max_value)
    if sched.value_type == "yes_no":
        if value not in (0, 1):
            raise ValueError("Answer yes or no")
        return value, None, value == 1
    text = (answer or "").strip()
    if sched.value_type in ("date", "time"):
        try:
            parsed = date.fromisoformat(text) if sched.value_type == "date" else time.fromisoformat(text)
        except ValueError:
            raise ValueError(f"Enter a valid {sched.value_type}") from None
        return None, parsed.isoformat() if sched.value_type == "date" else parsed.strftime("%H:%M"), True
    if not text:
        raise ValueError("Enter an answer")
    if sched.value_type == "choice":
        if text not in (sched.options or []):
            raise ValueError("Choose one of the listed answers")
        return None, text, text not in (sched.fail_options or [])
    if len(text) > (sched.max_length or 500):
        raise ValueError(f"The answer can be at most {sched.max_length or 500} characters")
    return None, text, True


def applies_on(schedule: EquipmentSchedule, day) -> bool:
    """Whether the check is due on this local date, by weekday list and day of month."""
    if schedule.weekdays and str(day.weekday()) not in schedule.weekdays.split(","):
        return False
    return schedule.day_of_month is None or day.day == schedule.day_of_month


def expected_slots(schedule: EquipmentSchedule, shift: Shift | None, tz: str, day) -> list[datetime]:
    """UTC check times for one schedule on a location-local date; none when the check is not due that day."""
    if schedule.timing == "manual" or not applies_on(schedule, day):
        return []
    start = schedule.time_of_day or (shift.start_time if shift else DEFAULT_START)
    first = timeutil.local_to_utc(day, start, tz)
    if schedule.timing != "interval" or not schedule.interval_minutes:
        return [first]
    end = (timeutil.shift_end_utc(day, shift.start_time, shift.end_time, tz) if shift
           else timeutil.local_to_utc(day + timedelta(days=1), time(0, 0), tz))
    slots, current = [], first
    while current < end:
        slots.append(current)
        current += timedelta(minutes=schedule.interval_minutes)
    return slots


def has_reading(sorted_times: list[datetime], low: datetime, high: datetime) -> bool:
    """Whether any time lies in [low, high); a binary search over a sorted list, so O(log n) rather than a scan."""
    i = bisect_left(sorted_times, low)
    return i < len(sorted_times) and sorted_times[i] < high


def window_low(slot: datetime, first: bool, day_start: datetime, grace: timedelta) -> datetime:
    """Where a slot's window opens; the first slot of the day also accepts a reading from earlier that day."""
    return min(day_start, slot - grace) if first else slot - grace


def slot_status(slot: datetime, upper: datetime, readings: list[datetime], now: datetime, grace: int, low: datetime | None = None) -> str:
    """`readings` must be sorted; `low` is where the slot's window opens, a grace period before the slot when not given."""
    window_start = low or slot - timedelta(minutes=grace)
    if has_reading(readings, window_start, upper):
        return "done"
    if now < slot:
        return "upcoming"
    return "due" if now <= slot + timedelta(minutes=grace) else "overdue"


def due_checks(db: Session, equipment: list[Equipment], now: datetime) -> list[dict]:
    """Every expected check today for the given equipment, with done/due/overdue/upcoming status.

    Schedules and readings of all the points come from two queries and are grouped in dictionaries, instead of
    two queries per point and per schedule.
    """
    grace = get_setting(db, "temp.due_grace_minutes")
    shifts, locations = shifts_by_id(db), locations_by_id(db)
    active = [eq for eq in equipment if eq.active]
    if not active:
        return []
    schedules: dict[int, list[EquipmentSchedule]] = defaultdict(list)
    for sched in db.scalars(select(EquipmentSchedule).where(EquipmentSchedule.equipment_id.in_([eq.id for eq in active]),
                                                            EquipmentSchedule.active.is_(True),
                                                            EquipmentSchedule.phase.is_distinct_from("finish"),
                                                            EquipmentSchedule.required.is_(True)).order_by(EquipmentSchedule.id)):
        schedules[sched.equipment_id].append(sched)
    starts = {}
    for eq in active:
        tz = locations[eq.location_id].timezone
        starts[eq.id] = timeutil.local_to_utc(timeutil.local_date(now, tz), time(0, 0), tz) - timedelta(minutes=grace)
    times: dict[int, list[datetime]] = defaultdict(list)
    ids = [s.id for scheds in schedules.values() for s in scheds]
    if ids:
        for schedule_id, recorded_at in db.execute(select(TemperatureReading.schedule_id, TemperatureReading.recorded_at).where(
                TemperatureReading.schedule_id.in_(ids), TemperatureReading.retest_of_id.is_(None), TemperatureReading.rejected_at.is_(None),
                TemperatureReading.recorded_at >= min(starts.values()))):
            times[schedule_id].append(recorded_at)
    out = []
    for eq in active:
        tz = locations[eq.location_id].timezone
        day = timeutil.local_date(now, tz)
        if is_closed(db, eq.location_id, day):
            continue  # a closed day expects no checks
        day_start = timeutil.local_to_utc(day, time(0, 0), tz)
        end_of_day = timeutil.local_to_utc(day + timedelta(days=1), time(0, 0), tz)
        for sched in schedules[eq.id]:
            slots = expected_slots(sched, shifts.get(sched.shift_id), tz, day)
            mine = sorted(t for t in times[sched.id] if t >= starts[eq.id])
            for i, slot in enumerate(slots):
                upper = slots[i + 1] if i + 1 < len(slots) else end_of_day
                out.append({"equipment_id": eq.id, "equipment": eq.name, "location_id": eq.location_id,
                            "schedule_id": sched.id, "stage": sched.stage,
                            "slot_at": slot.isoformat() + "Z", "opens_at": (slot - timedelta(minutes=grace)).isoformat() + "Z", "open": slot - timedelta(minutes=grace) <= now,
                            "status": slot_status(slot, upper, mine, now, grace, window_low(slot, i == 0, day_start, timedelta(minutes=grace)))})
    return out


def already_recorded(db: Session, eq: Equipment, sched: EquipmentSchedule, now: datetime) -> bool:
    """Whether the check's current scheduled time already has a reading; on-demand and time-out checks never do."""
    if sched.timing == "manual" or sched.phase == "finish":
        return False
    grace = get_setting(db, "temp.due_grace_minutes")
    location = db.get(Location, eq.location_id)
    tz, day = location.timezone, timeutil.local_date(now, location.timezone)
    slots = expected_slots(sched, db.get(Shift, sched.shift_id) if sched.shift_id else None, tz, day)
    started = [i for i, slot in enumerate(slots) if slot - timedelta(minutes=grace) <= now]
    if not started:
        return False
    i = started[-1]
    upper = slots[i + 1] if i + 1 < len(slots) else timeutil.local_to_utc(day + timedelta(days=1), time(0, 0), tz)
    low = window_low(slots[i], i == 0, timeutil.local_to_utc(day, time(0, 0), tz), timedelta(minutes=grace))
    times = sorted(db.scalars(select(TemperatureReading.recorded_at).where(
        TemperatureReading.schedule_id == sched.id, TemperatureReading.retest_of_id.is_(None), TemperatureReading.rejected_at.is_(None),
        TemperatureReading.recorded_at >= low, TemperatureReading.recorded_at < upper)))
    return has_reading(times, low, upper)


def closed_until(db: Session, eq: Equipment, sched: EquipmentSchedule, now: datetime) -> datetime | None:
    """When a scheduled check opens for recording, or none if it is open now, has no set time today or is a time in or out log."""
    if sched.timing == "manual" or sched.phase:
        return None
    location = db.get(Location, eq.location_id)
    day = timeutil.local_date(now, location.timezone)
    slots = expected_slots(sched, db.get(Shift, sched.shift_id) if sched.shift_id else None, location.timezone, day)
    opens = timedelta(minutes=get_setting(db, "temp.due_grace_minutes"))
    if not slots or any(slot - opens <= now for slot in slots):
        return None
    return slots[0] - opens


def pending_entries(db: Session, equipment: list[Equipment], now: datetime) -> list[dict]:
    """Time-in entries of two-step logs that still wait for their time out, oldest first."""
    points = {eq.id: eq for eq in equipment if eq.active}
    if not points:
        return []
    lead: dict[int, int] = {}
    has_finish: set[int] = set()
    for equipment_id, schedule_id, phase in db.execute(select(EquipmentSchedule.equipment_id, EquipmentSchedule.id, EquipmentSchedule.phase).where(
            EquipmentSchedule.equipment_id.in_(points), EquipmentSchedule.active.is_(True), EquipmentSchedule.phase.is_not(None)).order_by(EquipmentSchedule.id)):
        if phase == "start":
            lead.setdefault(equipment_id, schedule_id)
        else:
            has_finish.add(equipment_id)
    lead_ids = [schedule_id for equipment_id, schedule_id in lead.items() if equipment_id in has_finish]
    if not lead_ids:
        return []
    closed = select(TemperatureReading.start_reading_id).where(TemperatureReading.start_reading_id.is_not(None))
    entries = db.scalars(select(TemperatureReading).where(
        TemperatureReading.schedule_id.in_(lead_ids), TemperatureReading.retest_of_id.is_(None), TemperatureReading.rejected_at.is_(None),
        TemperatureReading.id.not_in(closed)).order_by(TemperatureReading.recorded_at).limit(200))
    return [{"start_reading_id": r.id, "equipment_id": r.equipment_id, "equipment": points[r.equipment_id].name,
             "location_id": r.location_id, "item": r.reference, "started_at": r.recorded_at.isoformat() + "Z",
             "minutes_open": int((now - r.recorded_at).total_seconds() // 60)} for r in entries]


def resolve_alerts(db: Session, reading_id: int, now: datetime) -> None:
    db.execute(update(Notification).where(Notification.dedupe_key == f"temp_fail:{reading_id}",
                                          Notification.resolved_at.is_(None)).values(resolved_at=now))


def resolve_chain(db: Session, reading: TemperatureReading, now: datetime) -> None:
    """A passing retest closes the open corrective action on every earlier reading in its chain."""
    previous_id = reading.retest_of_id
    while previous_id:
        for action in db.scalars(select(CorrectiveAction).where(CorrectiveAction.reading_id == previous_id,
                                                                CorrectiveAction.status.not_in(CLOSED_ACTIONS))):
            action.status, action.resolved_at = "resolved", now
        resolve_alerts(db, previous_id, now)
        previous_id = db.scalar(select(TemperatureReading.retest_of_id).where(TemperatureReading.id == previous_id))


def failure_counts(db: Session, equipment_ids: list[int], now: datetime) -> dict[int, int]:
    """Recent failed readings per point from one grouped query, for the points that have any."""
    if not equipment_ids:
        return {}
    since = now - timedelta(days=get_setting(db, "temp.repeat_failure_days"))
    return dict(db.execute(select(TemperatureReading.equipment_id, func.count()).where(
        TemperatureReading.equipment_id.in_(equipment_ids), TemperatureReading.passed.is_(False), TemperatureReading.rejected_at.is_(None),
        TemperatureReading.recorded_at >= since).group_by(TemperatureReading.equipment_id)).all())


def failure_count(db: Session, equipment_id: int, now: datetime) -> int:
    since = now - timedelta(days=get_setting(db, "temp.repeat_failure_days"))
    return db.scalar(select(func.count()).select_from(TemperatureReading).where(
        TemperatureReading.equipment_id == equipment_id, TemperatureReading.passed.is_(False), TemperatureReading.rejected_at.is_(None),
        TemperatureReading.recorded_at >= since))
