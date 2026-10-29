from bisect import bisect_right
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import NamedTuple

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from .. import timeutil
from ..models import (AbsenceRecord, AttendanceRecord, BreakageIncident, ChecklistInstance, ChecklistTask, ChecklistTemplate,
                      CorrectiveAction, Employee, Equipment, EquipmentSchedule, InventoryBalance, InventoryCategory, InventoryItem,
                      InventoryTransfer, InventoryTransferLine, Location, Receipt, ReceiptLine, Shift, ShiftAssignment, StockTransaction, Supplier, TemperatureReading)
from .checklists import overdue_after
from .inventory import level_map
from .settings import get_setting
from .monitoring import CLOSED_ACTIONS, expected_slots, has_reading, window_low
from .reference import employee_names, locations_by_id, shifts_by_id

DONE = ("completed", "verified", "pending_verification")
OPEN_STATES = ("not_started", "in_progress", "overdue")
MAX_DAYS = 366


@dataclass
class Win:
    """One location over a local-date range, with the matching UTC bounds."""

    loc: Location
    d_from: date
    d_to: date
    start: datetime
    end: datetime
    today: date


def windows_by(db: Session, now: datetime, scope: set[int] | None, location_id: int | None, span) -> list[Win]:
    """One window per location; `span(local_today)` returns that location's (from, to) local dates."""
    out = []
    for loc in sorted((l for l in locations_by_id(db).values() if l.active), key=lambda l: l.name):
        if (location_id is not None and loc.id != location_id) or (scope is not None and loc.id not in scope):
            continue
        tz = loc.timezone
        today = timeutil.local_date(now, tz)
        d_from, d_to = span(today)
        if d_to < d_from:
            raise ValueError("End date is before start date")
        if (d_to - d_from).days >= MAX_DAYS:
            raise ValueError(f"Date range is limited to {MAX_DAYS} days")
        out.append(Win(loc, d_from, d_to, timeutil.local_to_utc(d_from, time(0), tz),
                       timeutil.local_to_utc(d_to + timedelta(days=1), time(0), tz), today))
    return out


def windows(db: Session, now: datetime, scope: set[int] | None, location_id: int | None, d_from: date,
            d_to: date) -> list[Win]:
    return windows_by(db, now, scope, location_id, lambda _today: (d_from, d_to))


def week_of(day: date) -> tuple[date, date]:
    monday = day - timedelta(days=day.weekday())
    return monday, monday + timedelta(days=6)


def daterange(a: date, b: date):
    for n in range((b - a).days + 1):
        yield a + timedelta(days=n)


def pct(numerator: int, denominator: int) -> float | None:
    return round(100 * numerator / denominator, 1) if denominator else None


def classify(inst: ChecklistInstance, now: datetime) -> str:
    if inst.status in DONE or inst.status in ("waived", "failed"):
        return inst.status
    return "overdue" if inst.due_at and inst.due_at < now else "upcoming"


def compliance(counts: Counter) -> dict:
    """Done work over work that is due: future tasks and waived tasks are excluded from the denominator."""
    numerator = sum(counts[s] for s in DONE)
    denominator = numerator + counts["failed"] + counts["overdue"]
    return {"numerator": numerator, "denominator": denominator, "percent": pct(numerator, denominator)}


def checklist_stats(db: Session, win: Win, now: datetime, employee_id: int | None = None,
                    frequency: str | None = None, not_frequency: str | None = None) -> dict:
    stmt = (select(ChecklistInstance, ChecklistTask, ChecklistTemplate)
            .join(ChecklistTask, ChecklistTask.id == ChecklistInstance.task_id)
            .join(ChecklistTemplate, ChecklistTemplate.id == ChecklistTask.template_id)
            .where(ChecklistInstance.location_id == win.loc.id, ChecklistInstance.local_date >= win.d_from,
                   ChecklistInstance.local_date <= win.d_to))
    if frequency:
        stmt = stmt.where(ChecklistTemplate.frequency == frequency)
    if not_frequency:
        stmt = stmt.where(ChecklistTemplate.frequency != not_frequency)
    if employee_id is not None:
        emp = db.get(Employee, employee_id)
        stmt = stmt.where((ChecklistInstance.assigned_employee_id == employee_id)
                          | (ChecklistInstance.completed_by == (emp.user_id if emp else -1)))
    rows = db.execute(stmt.order_by(ChecklistInstance.local_date, ChecklistInstance.due_at)).all()
    counts: Counter = Counter()
    per_day: dict[date, Counter] = defaultdict(Counter)
    rows_out = []
    late_now = overdue_after(db, now)
    for inst, task, tpl in rows:
        state = classify(inst, late_now)
        counts[state] += 1
        per_day[inst.local_date][state] += 1
        rows_out.append((inst, task, tpl, state))
    return {"counts": counts, **compliance(counts), "per_day": per_day, "rows": rows_out}


LEAVE_TYPES = ("sick_leave", "annual_leave", "unpaid_leave", "other_leave")
ATTENDANCE_KEYS = ("scheduled", "present", "late", "absent", "on_leave", "week_off")


def attendance_stats(db: Session, win: Win, now: datetime, employee_id: int | None = None) -> dict:
    """Expected employee-days from assignments versus actual records; future days are never counted as absent.

    `scheduled` is the days someone was required to attend: week offs and recorded leave are reported separately,
    a recorded absence counts as absent, and a missing check-in with no record is absent but flagged unrecorded.
    """
    last = min(win.d_to, win.today)
    tz = win.loc.timezone
    empty = {"rows": [], "per_day": {}, **{k: 0 for k in ATTENDANCE_KEYS}}
    if last < win.d_from:
        return empty
    emp_filter = (Employee.id == employee_id,) if employee_id is not None else ()
    assigns = db.execute(
        select(ShiftAssignment, Employee, Shift).join(Employee, Employee.id == ShiftAssignment.employee_id)
        .join(Shift, Shift.id == ShiftAssignment.shift_id)
        .where(ShiftAssignment.location_id == win.loc.id, Employee.status == "active", *emp_filter)).all()
    records = {}
    for rec in db.scalars(select(AttendanceRecord).where(
            AttendanceRecord.location_id == win.loc.id, AttendanceRecord.local_date >= win.d_from,
            AttendanceRecord.local_date <= last, *((AttendanceRecord.employee_id == employee_id,) if employee_id is not None else ()))):
        records.setdefault((rec.employee_id, rec.local_date), rec)
    # a rostered person who worked at another outlet that day is not absent here; the other outlet counts the day
    elsewhere = {(emp_id, day): place for emp_id, day, place in db.execute(
        select(AttendanceRecord.employee_id, AttendanceRecord.local_date, Location.name).join(Location, Location.id == AttendanceRecord.location_id)
        .where(AttendanceRecord.location_id != win.loc.id, AttendanceRecord.local_date >= win.d_from, AttendanceRecord.local_date <= last,
               *((AttendanceRecord.employee_id == employee_id,) if employee_id is not None else ())))}
    absences = {(a.employee_id, a.local_date): a for a in db.scalars(select(AbsenceRecord).where(
        AbsenceRecord.location_id == win.loc.id, AbsenceRecord.local_date >= win.d_from, AbsenceRecord.local_date <= last,
        AbsenceRecord.voided_at.is_(None), *((AbsenceRecord.employee_id == employee_id,) if employee_id is not None else ())))}
    names, shifts = employee_names(db), shifts_by_id(db)
    missed_hours = get_setting(db, "attendance.missed_checkout_hours")
    expected: dict[tuple[int, date], tuple[ShiftAssignment, Shift]] = {}
    off_days: dict[tuple[int, date], Shift] = {}
    for day in daterange(win.d_from, last):
        for a, emp, shift in assigns:
            if not a.applies_on(day):
                continue
            if shift.kind == "weekoff":
                off_days[(emp.id, day)] = shift
                continue
            current = expected.get((emp.id, day))
            if current is None or shift.start_time < current[1].start_time:
                expected[(emp.id, day)] = (a, shift)
    rows = []
    per_day: dict[date, dict] = defaultdict(lambda: {k: 0 for k in ATTENDANCE_KEYS})
    totals = {k: 0 for k in ATTENDANCE_KEYS}

    def count(day, key):
        per_day[day][key] += 1
        totals[key] += 1

    def row(emp_id, day, shift, rec, status, recorded=None, note=None):
        return {"employee_id": emp_id, "name": names.get(emp_id), "day": day, "shift": shift.name if shift else None,
                "status": status, "recorded": recorded, "note": note or (rec.exception_reason if rec else None),
                "check_in": rec.check_in_at if rec else None, "check_out": rec.check_out_at if rec else None,
                "late_minutes": rec.late_minutes if rec else 0, "payable_minutes": rec.payable_minutes if rec else None,
                "overtime_minutes": rec.overtime_minutes if rec else None, "geo_flags": rec.geo_flags if rec else []}

    for (emp_id, day), (_, shift) in sorted(expected.items(), key=lambda kv: (kv[0][1], names.get(kv[0][0], ""))):
        rec = records.get((emp_id, day))
        absence = absences.get((emp_id, day))
        if rec:
            count(day, "scheduled")
            status = "late" if rec.late_minutes > 0 else "present"
            if rec.open_flag == 1:
                status = "missed_checkout" if (now - rec.check_in_at).total_seconds() > missed_hours * 3600 else "on_duty"
            count(day, "present")
            if rec.late_minutes > 0:
                count(day, "late")
            rows.append(row(emp_id, day, shift, rec, status))
        elif absence and absence.absence_type == "day_off":
            count(day, "week_off")
            rows.append(row(emp_id, day, shift, None, "week_off", True, absence.note))
        elif absence and absence.absence_type in LEAVE_TYPES:
            count(day, "on_leave")
            rows.append(row(emp_id, day, shift, None, absence.absence_type, True, absence.note))
        elif absence:
            count(day, "scheduled")
            count(day, "absent")
            rows.append(row(emp_id, day, shift, None, "absent", True, absence.note))
        elif (emp_id, day) in elsewhere:
            rows.append(row(emp_id, day, shift, None, "worked_elsewhere", True, f"Worked at {elsewhere[(emp_id, day)]}"))
        else:
            count(day, "scheduled")
            start = timeutil.local_to_utc(day, shift.start_time, tz)
            if day < win.today or now > start + timedelta(minutes=shift.grace_minutes):
                count(day, "absent")
                rows.append(row(emp_id, day, shift, None, "absent", False))
            else:
                rows.append(row(emp_id, day, shift, None, "not_yet_due"))
    for (emp_id, day), shift in sorted(off_days.items(), key=lambda kv: (kv[0][1], names.get(kv[0][0], ""))):
        if (emp_id, day) in expected:
            continue
        rec = records.get((emp_id, day))
        if rec:
            rows.append(row(emp_id, day, shifts.get(rec.shift_id), rec, "unscheduled"))
            continue
        count(day, "week_off")
        rows.append(row(emp_id, day, shift, None, "week_off"))
    for (emp_id, day), rec in records.items():
        if (emp_id, day) not in expected and (emp_id, day) not in off_days:
            rows.append(row(emp_id, day, shifts.get(rec.shift_id), rec, "unscheduled"))
    for (emp_id, day), absence in absences.items():
        if (emp_id, day) not in expected:
            is_off = absence.absence_type == "day_off"
            if is_off:
                count(day, "week_off")
            rows.append(row(emp_id, day, None, None, "week_off" if is_off else absence.absence_type, True, absence.note))
    return {"rows": rows, "per_day": dict(per_day), **totals}


def monitoring_stats(db: Session, win: Win, now: datetime, equipment_id: int | None = None) -> dict:
    """Checks due so far versus recorded, per equipment, plus failed readings in the window.

    The schedules and the readings of every point come from two queries and are grouped by point and schedule.
    """
    grace = timedelta(minutes=get_setting(db, "temp.due_grace_minutes"))
    stmt = select(Equipment).where(Equipment.location_id == win.loc.id, Equipment.active.is_(True))
    if equipment_id is not None:
        stmt = stmt.where(Equipment.id == equipment_id)
    points = list(db.scalars(stmt.order_by(Equipment.code)))
    shifts = shifts_by_id(db)
    last = min(win.d_to, win.today)
    schedules: dict[int, list[EquipmentSchedule]] = defaultdict(list)
    readings: dict[int, list] = defaultdict(list)
    if points:
        ids = [eq.id for eq in points]
        for sched in db.scalars(select(EquipmentSchedule).where(EquipmentSchedule.equipment_id.in_(ids), EquipmentSchedule.active.is_(True),
                                                                EquipmentSchedule.phase.is_distinct_from("finish"), EquipmentSchedule.required.is_(True))):
            schedules[sched.equipment_id].append(sched)
        # only the columns used, as plain tuples: thousands of full objects are not needed to count and match times
        for row_ in db.execute(select(TemperatureReading.equipment_id, TemperatureReading.schedule_id, TemperatureReading.recorded_at,
                                      TemperatureReading.passed, TemperatureReading.retest_of_id).where(
                TemperatureReading.equipment_id.in_(ids), TemperatureReading.recorded_at >= win.start - grace,
                TemperatureReading.recorded_at < win.end, TemperatureReading.rejected_at.is_(None))):
            readings[row_.equipment_id].append(row_)
    out: dict[int, dict] = {}
    for eq in points:
        entry = {"equipment_id": eq.id, "equipment": eq.name, "location": win.loc.name, "due": 0, "done": 0, "missed": 0,
                 "failed": 0, "readings": 0}
        mine = readings[eq.id]
        entry["readings"] = sum(1 for r in mine if win.start <= r.recorded_at < win.end)
        entry["failed"] = sum(1 for r in mine if not r.passed and win.start <= r.recorded_at < win.end)
        if last >= win.d_from:
            first_reads: dict[int, list[datetime]] = defaultdict(list)  # reading times per schedule, sorted for binary search
            for r in mine:
                if r.retest_of_id is None:
                    first_reads[r.schedule_id].append(r.recorded_at)
            for times in first_reads.values():
                times.sort()
            for sched in schedules[eq.id]:
                times = first_reads.get(sched.id, [])
                for day in daterange(win.d_from, last):
                    slots = expected_slots(sched, shifts.get(sched.shift_id), win.loc.timezone, day)
                    day_start = timeutil.local_to_utc(day, time(0), win.loc.timezone)
                    day_end = timeutil.local_to_utc(day + timedelta(days=1), time(0), win.loc.timezone)
                    for i, slot in enumerate(slots):
                        if slot > now:
                            continue
                        upper = slots[i + 1] if i + 1 < len(slots) else day_end
                        entry["due"] += 1
                        if has_reading(times, window_low(slot, i == 0, day_start, grace), upper):
                            entry["done"] += 1
                        elif now > slot + grace:
                            entry["missed"] += 1
        out[eq.id] = entry
    due = sum(e["due"] for e in out.values())
    done = sum(e["done"] for e in out.values())
    return {"equipment": out, "due": due, "done": done, "missed": sum(e["missed"] for e in out.values()),
            "failed": sum(e["failed"] for e in out.values()), "percent": pct(done, due)}


def stock_snapshot(db: Session, scope: set[int] | None, location_id: int | None = None) -> dict:
    ids = {location_id} if location_id is not None else scope
    stmt = select(InventoryBalance, InventoryItem).join(InventoryItem, InventoryItem.id == InventoryBalance.item_id)
    if ids is not None:
        stmt = stmt.where(InventoryBalance.location_id.in_(ids))
    total = {"qty": 0, "value": 0.0}
    low = []
    levels = level_map(db)
    for balance, item in db.execute(stmt).all():
        total["qty"] += balance.qty
        unit = balance.avg_cost if balance.avg_cost is not None else item.unit_cost
        total["value"] += float(balance.qty * unit) if unit is not None else 0.0
        minimum = levels.get((item.id, balance.location_id), item.min_level)
        if item.active and balance.qty < minimum:
            low.append({"item_id": item.id, "code": item.code, "name": item.name,
                        "location_id": balance.location_id, "qty": balance.qty, "min_level": minimum,
                        "target_level": item.target_level})
    total["value"] = round(total["value"], 3)
    return {"total": total, "low": low}


class Move(NamedTuple):
    txn_type: str
    qty_delta: int
    day: date
    location_id: int
    item_id: int


def day_finder(win: Win):
    """A function from a UTC time inside the window to its local date, by binary search over the day starts.

    The start of every local day is worked out once, so a daylight-saving change is handled exactly and each lookup
    is a bisect instead of a time zone conversion.
    """
    days = list(daterange(win.d_from, win.d_to))
    starts = [timeutil.local_to_utc(d, time(0), win.loc.timezone) for d in days]
    return lambda moment: days[bisect_right(starts, moment) - 1]


RECEIPT_REFS = ("receipt", "receipt_void")


def movement_kind(txn_type: str, ref_type: str | None) -> str:
    """The name a movement goes by in charts and reports: a supplier return and a voided invoice are not 'issue' or 'adjustment'."""
    if ref_type == "receipt" and txn_type == "issue":
        return "supplier_return"
    if ref_type == "receipt_void":
        return "receipt_void"
    return txn_type


def receipt_window(win: Win, date_by: str, entered_at=StockTransaction.occurred_at):
    """Which receipts fall in the window by the date a person means (invoice or received), else by when they were entered."""
    entered = and_(entered_at >= win.start, entered_at < win.end)
    if date_by == "received":
        return or_(and_(Receipt.received_on.is_not(None), Receipt.received_on >= win.d_from, Receipt.received_on <= win.d_to),
                   and_(Receipt.received_on.is_(None), entered))
    first, after = datetime.combine(win.d_from, time.min), datetime.combine(win.d_to + timedelta(days=1), time.min)
    return or_(and_(Receipt.invoice_date.is_not(None), Receipt.invoice_date >= first, Receipt.invoice_date < after),
               and_(Receipt.invoice_date.is_(None), entered))


def movements(db: Session, wins: list[Win], date_by: str | None = None) -> list[Move]:
    """Stock movements in the windows with their local day; only the columns used are read, as plain tuples.

    With `date_by` ("invoice" or "received") a delivery and its voiding sit on the invoice or received date of the
    document instead of the moment it was entered, so a late-entered invoice lands on the day it belongs to.
    """
    out = []
    for win in wins:
        day_of = day_finder(win)
        columns = (StockTransaction.txn_type, StockTransaction.qty_delta, StockTransaction.occurred_at, StockTransaction.item_id, StockTransaction.ref_type)
        plain = select(*columns).where(StockTransaction.location_id == win.loc.id, StockTransaction.occurred_at >= win.start,
                                       StockTransaction.occurred_at < win.end)
        if date_by:
            plain = plain.where(or_(StockTransaction.ref_type.is_(None), StockTransaction.ref_type.not_in((*RECEIPT_REFS, "breakage"))))
        for txn_type, qty_delta, occurred_at, item_id, ref_type in db.execute(plain):
            out.append(Move(movement_kind(txn_type, ref_type), qty_delta, day_of(occurred_at), win.loc.id, item_id))
        if not date_by:
            continue
        # breakage counts on the day it was reported, not the day it was approved
        for txn_type, qty_delta, _, item_id, ref_type, reported in db.execute(
                select(*columns, BreakageIncident.occurred_at).join(BreakageIncident, BreakageIncident.id == StockTransaction.ref_id)
                .where(StockTransaction.location_id == win.loc.id, StockTransaction.ref_type == "breakage",
                       BreakageIncident.occurred_at >= win.start, BreakageIncident.occurred_at < win.end)):
            out.append(Move(movement_kind(txn_type, ref_type), qty_delta, day_of(reported), win.loc.id, item_id))
        documents = select(*columns, Receipt.invoice_date, Receipt.received_on).join(Receipt, Receipt.id == StockTransaction.ref_id).where(
            StockTransaction.location_id == win.loc.id, StockTransaction.ref_type.in_(RECEIPT_REFS), receipt_window(win, date_by))
        for txn_type, qty_delta, occurred_at, item_id, ref_type, invoiced, received_on in db.execute(documents):
            made = invoiced.date() if date_by == "invoice" and invoiced else received_on if date_by == "received" and received_on else None
            out.append(Move(movement_kind(txn_type, ref_type), qty_delta, made or day_of(occurred_at), win.loc.id, item_id))
    return out


def breakage_in(db: Session, wins: list[Win]) -> list[tuple[BreakageIncident, date]]:
    out = []
    for win in wins:
        day_of = day_finder(win)
        for inc in db.scalars(select(BreakageIncident).where(
                BreakageIncident.location_id == win.loc.id, BreakageIncident.occurred_at >= win.start,
                BreakageIncident.occurred_at < win.end, BreakageIncident.status != "rejected")
                .order_by(BreakageIncident.id)):
            out.append((inc, day_of(inc.occurred_at)))
    return out


def open_actions(db: Session, location_ids: set[int] | None) -> int:
    stmt = select(CorrectiveAction).join(TemperatureReading, TemperatureReading.id == CorrectiveAction.reading_id).where(
        CorrectiveAction.status.not_in(CLOSED_ACTIONS))
    if location_ids is not None:
        stmt = stmt.where(TemperatureReading.location_id.in_(location_ids))
    return len(db.scalars(stmt).all())


DAILY_GRAIN_DAYS = 62


def stock_insights(db: Session, wins: list[Win], d_from: date, d_to: date, date_by: str = "invoice") -> dict:
    """Stock in and out, breakage and transfers over a range, grouped by day or by month for long ranges."""
    monthly = (d_to - d_from).days >= DAILY_GRAIN_DAYS
    key = (lambda d: d.strftime("%Y-%m")) if monthly else (lambda d: d.isoformat())
    periods = sorted({key(d) for d in daterange(d_from, d_to)})
    moves = {p: {"date": p, "in": 0, "out": 0} for p in periods}
    by_type: Counter = Counter()
    for move in movements(db, wins, date_by):
        if move.txn_type == "opening":
            continue
        by_type[move.txn_type] += abs(move.qty_delta)
        if len(wins) > 1 and move.txn_type in ("transfer_in", "transfer_out"):
            continue  # across several locations a transfer is one move out and one in, not stock arriving or leaving
        slot = moves[key(move.day)]
        slot["in" if move.qty_delta > 0 else "out"] += abs(move.qty_delta)
    breakage = {p: {"period": p, "incidents": 0, "qty": 0, "est_cost": 0.0} for p in periods}
    reasons: Counter = Counter()
    top_items: Counter = Counter()
    names = {i.id: i.name for i in db.scalars(select(InventoryItem))}
    for inc, day in breakage_in(db, wins):
        slot = breakage[key(day)]
        slot["incidents"] += 1
        slot["qty"] += inc.qty
        slot["est_cost"] = round(slot["est_cost"] + float(inc.est_cost or 0), 3)
        reasons[inc.reason or "No reason given"] += inc.qty
        top_items[names.get(inc.item_id, "Unknown item")] += inc.qty
    places = {w.loc.id: w.loc.name for w in wins}
    first = wins[0] if wins else None
    transfers = {"requested": 0, "completed": 0, "rejected": 0, "units": 0}
    routes: dict[str, dict] = {}
    if first:
        start, end = min(w.start for w in wins), max(w.end for w in wins)
        all_places = {loc.id: loc.name for loc in db.scalars(select(Location))}
        for t in db.scalars(select(InventoryTransfer).where(InventoryTransfer.requested_at >= start, InventoryTransfer.requested_at < end)):
            if t.from_location_id not in places and t.to_location_id not in places:
                continue
            transfers[t.status if t.status in transfers else "requested"] += 1
            units = sum(ln.qty for ln in db.scalars(select(InventoryTransferLine).where(InventoryTransferLine.transfer_id == t.id)))
            if t.status == "completed":
                transfers["units"] += units
                route = routes.setdefault(f"{all_places.get(t.from_location_id)} to {all_places.get(t.to_location_id)}", {"count": 0, "qty": 0})
                route["count"] += 1
                route["qty"] += units
    top = lambda counter: [{"label": k, "value": v} for k, v in counter.most_common(6)]  # noqa: E731
    return {"range": {"from": d_from.isoformat(), "to": d_to.isoformat(), "grain": "month" if monthly else "day"},
            "movement": list(moves.values()), "movement_by_type": [{"label": k.replace("_", " ").capitalize(), "value": v} for k, v in by_type.most_common()],
            "breakage_trend": list(breakage.values()), "breakage_by_reason": top(reasons), "breakage_top_items": top(top_items),
            "transfers": transfers, "transfer_routes": [{"label": k, "value": v["qty"], "sub": f"{v['count']} transfer(s)"} for k, v in sorted(routes.items(), key=lambda kv: -kv[1]["qty"])[:6]],
            "totals": {"in": sum(m["in"] for m in moves.values()), "out": sum(m["out"] for m in moves.values()),
                       "breakage_units": sum(b["qty"] for b in breakage.values()), "breakage_cost": round(sum(b["est_cost"] for b in breakage.values()), 3)}}


def stock_analysis(db: Session, wins: list[Win], d_from: date, d_to: date, date_by: str = "invoice") -> dict:
    """What was bought, from whom, what was used most, and what stock is worth now, for the chosen places and dates."""
    monthly = (d_to - d_from).days >= DAILY_GRAIN_DAYS
    key = (lambda d: d.strftime("%Y-%m")) if monthly else (lambda d: d.isoformat())
    spend = {p: {"period": p, "spend": 0.0} for p in sorted({key(d) for d in daterange(d_from, d_to)})}
    by_supplier: Counter = Counter()
    by_category: Counter = Counter()
    categories = {c.id: c.name for c in db.scalars(select(InventoryCategory))}
    names = {i.id: (i.name, i.category_id) for i in db.scalars(select(InventoryItem))}
    suppliers = {s.id: s.name for s in db.scalars(select(Supplier))}
    for win in wins:
        day_of = day_finder(win)
        found = db.execute(select(Receipt.id, Receipt.supplier_id, Receipt.total, Receipt.invoice_date, Receipt.received_on, Receipt.received_at)
                           .where(Receipt.location_id == win.loc.id, Receipt.doc_type == "receipt", Receipt.status == "posted",
                                  Receipt.total.is_not(None), receipt_window(win, date_by, Receipt.received_at))).all()
        days = {}
        for rid, supplier_id, total, invoiced, received_on, received_at in found:
            day = invoiced.date() if date_by == "invoice" and invoiced else received_on if date_by == "received" and received_on else day_of(received_at)
            days[rid] = day
            spend[key(day)]["spend"] = round(spend[key(day)]["spend"] + float(total), 3)
            by_supplier[suppliers.get(supplier_id, "Unknown supplier")] += float(total)
        if days:
            # what each line really cost, as the ledger holds it, so the invoice discount is spread over the categories and they add up to the supplier total
            for item_id, qty, ledger_cost, line_total in db.execute(
                    select(ReceiptLine.item_id, ReceiptLine.qty, StockTransaction.unit_cost, ReceiptLine.line_total)
                    .outerjoin(StockTransaction, StockTransaction.id == ReceiptLine.transaction_id)
                    .where(ReceiptLine.receipt_id.in_(days), ReceiptLine.line_total.is_not(None))):
                by_category[categories.get(names.get(item_id, ("", None))[1], "Uncategorised")] += float(qty * ledger_cost) if ledger_cost is not None else float(line_total)
    used: Counter = Counter()
    for move in movements(db, wins, date_by):
        if move.txn_type == "issue" and move.qty_delta < 0:
            used[names.get(move.item_id, ("Unknown item", None))[0]] += abs(move.qty_delta)
    held: Counter = Counter()
    ids = [w.loc.id for w in wins]
    for item_id, qty, avg in db.execute(select(InventoryBalance.item_id, InventoryBalance.qty, InventoryBalance.avg_cost).where(InventoryBalance.location_id.in_(ids))):
        if qty > 0:
            item = db.get(InventoryItem, item_id)
            price = avg if avg is not None else item.unit_cost
            held[categories.get(item.category_id, "Uncategorised")] += float(qty * (price or 0))
    top = lambda counter, n=6: [{"label": k, "value": round(v, 3)} for k, v in counter.most_common(n) if v]  # noqa: E731
    return {"range": {"grain": "month" if monthly else "day"}, "date_by": date_by, "spend_trend": list(spend.values()),
            "spend_by_supplier": top(by_supplier), "spend_by_category": top(by_category), "most_used_items": top(used),
            "stock_value_by_category": top(held, 8), "total_spend": round(sum(p["spend"] for p in spend.values()), 3)}
