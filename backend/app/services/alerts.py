from datetime import datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import timeutil
from ..models import (AbsenceRecord, AttendanceRecord, ChecklistInstance, ChecklistTask, CorrectiveAction, Employee, Equipment,
                      CountRound, EquipmentSchedule, Location, Notification, RoundCount, Shift, ShiftAssignment, TemperatureReading)
from ..permissions import MANAGER, STEWARD, SUPERVISOR
from . import summary
from .checklists import OPEN, alerts_for, is_closed, overdue_after
from .inventory import shortage_rows
from .notify import notify, recipients
from .settings import get_setting
from .monitoring import describe, due_checks, pending_entries

SUMMARY_HOUR = time(8, 0)


def _hm(utc: datetime, tz: str) -> str:
    return timeutil.to_local(utc, tz).strftime("%H:%M")


def missing_checkins(db: Session, location: Location, now: datetime) -> int:
    """Scheduled staff who have not checked in once their shift start plus grace has passed."""
    tz = location.timezone
    day = timeutil.local_date(now, tz)
    if is_closed(db, location.id, day):
        return 0
    rows = db.execute(
        select(ShiftAssignment, Employee, Shift).join(Employee, Employee.id == ShiftAssignment.employee_id)
        .join(Shift, Shift.id == ShiftAssignment.shift_id)
        .where(ShiftAssignment.location_id == location.id, ShiftAssignment.weekday == day.weekday(),
               Employee.status == "active", Shift.active.is_(True),
               Shift.kind == "work")).all()
    away = set(db.scalars(select(AbsenceRecord.employee_id).where(
        AbsenceRecord.local_date == day, AbsenceRecord.voided_at.is_(None))))
    created = 0
    for assignment, emp, shift in rows:
        if not assignment.applies_on(day):
            continue
        start = timeutil.local_to_utc(day, shift.start_time, tz)
        end = timeutil.shift_end_utc(day, shift.start_time, shift.end_time, tz)
        if not (start + timedelta(minutes=shift.grace_minutes) < now < end):
            continue
        if emp.id in away or db.scalar(select(AttendanceRecord.id).where(AttendanceRecord.employee_id == emp.id,
                                                                         AttendanceRecord.local_date == day)):
            continue
        targets = recipients(db, location.id, SUPERVISOR, MANAGER) + ([emp.user_id] if emp.user_id else [])
        created += notify(db, targets, "no_checkin", f"{emp.full_name} has not checked in ({shift.name} started {_hm(start, tz)})",
                          key=f"nocheckin:{emp.id}:{day}:{shift.id}", priority="high", location_id=location.id,
                          link="/attendance")
    return created


def missed_checkouts(db: Session, now: datetime) -> int:
    """Someone still checked in well after their shift should have ended (or, with no shift, a long time after checking in)."""
    created = 0
    for rec in db.scalars(select(AttendanceRecord).where(AttendanceRecord.open_flag == 1)):
        if not summary.checkout_overdue(db, rec, now):
            continue  # a night shift is not over until the morning
        emp = db.get(Employee, rec.employee_id)
        targets = recipients(db, rec.location_id, SUPERVISOR, MANAGER) + ([emp.user_id] if emp.user_id else [])
        created += notify(db, targets, "missed_checkout", f"{emp.full_name} has not checked out", key=f"missedout:{rec.id}",
                          priority="high", location_id=rec.location_id, link="/attendance")
    return created


def checklist_alerts(db: Session, location: Location, now: datetime) -> int:
    """Reminders before a deadline, an alert when it passes, then escalation to supervisor and manager."""
    lead = timedelta(minutes=get_setting(db, "reminder.lead_minutes"))
    to_supervisor = timedelta(minutes=get_setting(db, "escalation.supervisor_after_minutes"))
    to_manager = timedelta(minutes=get_setting(db, "escalation.manager_after_minutes"))
    tz = location.timezone
    rows = db.execute(
        select(ChecklistInstance, ChecklistTask).join(ChecklistTask, ChecklistTask.id == ChecklistInstance.task_id)
        .where(ChecklistInstance.location_id == location.id, ChecklistInstance.status.in_(OPEN + ("overdue",)),
               ChecklistInstance.due_at.is_not(None))).all()
    groups: dict[datetime, list[tuple[ChecklistInstance, ChecklistTask]]] = {}
    if is_closed(db, location.id, timeutil.local_date(now, tz)):
        return 0  # the place is closed today, so nothing is expected
    grace = now - overdue_after(db, now)
    for inst, task in rows:
        if alerts_for(db, task.priority):  # tasks below the chosen priority still show on screen, they just do not alert
            groups.setdefault(inst.due_at, []).append((inst, task))
    created = 0
    for due, members in groups.items():
        stamp, label = due.strftime("%Y%m%d%H%M"), _hm(due, tz)
        count = len(members)
        crew = recipients(db, location.id, STEWARD, SUPERVISOR)
        if due - lead <= now < due:
            created += notify(db, crew, "task_due_soon", f"{count} task(s) due at {label} - {location.name}",
                              key=f"approach:{location.id}:{stamp}", location_id=location.id, due_at=due, link="/checklists")
        if now >= due + grace:
            late = now - due
            created += notify(db, crew, "task_overdue", f"{count} task(s) overdue since {label} - {location.name}",
                              key=f"overdue:{location.id}:{stamp}", priority="high", location_id=location.id,
                              due_at=due, link="/checklists")
            if late >= to_supervisor:
                created += notify(db, recipients(db, location.id, SUPERVISOR), "task_escalated",
                                  f"Escalation: {count} task(s) still open since {label} - {location.name}",
                                  key=f"esc_sup:{location.id}:{stamp}", priority="high", location_id=location.id,
                                  due_at=due, link="/checklists")
            if late >= to_manager:
                created += notify(db, recipients(db, None, MANAGER), "task_escalated",
                                  f"Escalation to manager: {count} task(s) open since {label} - {location.name}",
                                  key=f"esc_mgr:{location.id}:{stamp}", priority="critical", location_id=location.id,
                                  due_at=due, link="/checklists", requires_ack=True)
        for inst, task in members:
            if now >= due + grace and inst.assigned_employee_id:
                emp = db.get(Employee, inst.assigned_employee_id)
                if emp and emp.user_id:
                    created += notify(db, [emp.user_id], "task_overdue", f"Your task is overdue: {task.description}",
                                      key=f"taskover:{inst.id}", priority="high", location_id=location.id, due_at=due,
                                      link="/checklists")
            if task.escalation_minutes is not None and now >= due + timedelta(minutes=task.escalation_minutes):
                created += notify(db, recipients(db, location.id, SUPERVISOR, MANAGER), "task_escalated",
                                  f"Escalation: {task.description}", key=f"esc_task:{inst.id}", priority="high",
                                  location_id=location.id, due_at=due, link="/checklists")
    return created


def monitoring_alerts(db: Session, location: Location, now: datetime) -> int:
    equipment = list(db.scalars(select(Equipment).where(Equipment.location_id == location.id, Equipment.active.is_(True))))
    created = 0
    checks = due_checks(db, equipment, now)
    # earlier overdue slots of a schedule are already missed; only the latest one is worth an alert
    latest_overdue = {c["schedule_id"]: c for c in checks if c["status"] == "overdue"}
    for check in checks:
        if check["status"] == "overdue" and latest_overdue[check["schedule_id"]] is not check:
            continue
        slot = check["slot_at"][:16].replace("-", "").replace(":", "").replace("T", "")
        title = f"{check['equipment']} - {check['stage']} check"
        if check["status"] == "due":
            created += notify(db, recipients(db, location.id, STEWARD, SUPERVISOR), "monitoring_due", f"Check due: {title}",
                              key=f"checkdue:{check['schedule_id']}:{slot}", location_id=location.id, link="/monitoring")
        elif check["status"] == "overdue":
            created += notify(db, recipients(db, location.id, SUPERVISOR, MANAGER), "monitoring_overdue",
                              f"Check overdue: {title}", key=f"checkover:{check['schedule_id']}:{slot}",
                              priority="high", location_id=location.id, link="/monitoring", requires_ack=True)
    return created


def corrective_alerts(db: Session, now: datetime) -> int:
    escalate_after = timedelta(minutes=get_setting(db, "temp.escalate_after_minutes"))
    created = 0
    rows = db.execute(select(CorrectiveAction, TemperatureReading).join(
        TemperatureReading, TemperatureReading.id == CorrectiveAction.reading_id)
        .join(Equipment, Equipment.id == TemperatureReading.equipment_id).join(Location, Location.id == TemperatureReading.location_id)
        .where(CorrectiveAction.status.in_(("action_required", "retest_due", "retest_failed")),
               Equipment.active.is_(True), Location.active.is_(True))).all()  # a point or place that is turned off sends nothing
    for action, reading in rows:
        if action.status == "retest_due" and action.retest_due_at and action.retest_due_at < now:
            created += notify(db, recipients(db, reading.location_id, SUPERVISOR) + [action.taken_by], "retest_due",
                              f"Retest overdue for {reading.stage}: {describe(reading)}", key=f"retest:{action.id}",
                              priority="critical", location_id=reading.location_id, link="/monitoring", requires_ack=True)
        if now - reading.recorded_at >= escalate_after and action.escalated_at is None:
            action.escalated_at = now
            created += notify(db, recipients(db, None, MANAGER), "monitoring_escalated",
                              f"Unresolved failed check ({describe(reading)}, {reading.stage})",
                              key=f"check_esc:{action.id}", priority="critical", location_id=reading.location_id,
                              link="/monitoring", requires_ack=True)
    return created


def pending_time_outs(db: Session, now: datetime) -> int:
    """Warns about time-in entries (defrosting, cooling) still waiting for their time out after the set number of hours."""
    limit = get_setting(db, "temp.pending_alert_hours")
    created = 0
    live = select(Equipment).join(Location, Location.id == Equipment.location_id).where(Equipment.active.is_(True), Location.active.is_(True))  # off means silent
    for entry in pending_entries(db, list(db.scalars(live)), now):
        if limit and entry["minutes_open"] >= limit * 60:
            created += notify(db, recipients(db, entry["location_id"], SUPERVISOR, MANAGER), "time_out_missing",
                              f"Time out still missing: {entry['item'] or entry['equipment']} ({entry['equipment']}), open {entry['minutes_open'] // 60} h",
                              key=f"pending_out:{entry['start_reading_id']}", priority="high", location_id=entry["location_id"],
                              link="/monitoring", requires_ack=True)
    return created


def low_stock(db: Session, now: datetime) -> int:
    created = 0
    for balance, item, minimum in shortage_rows(db):
        created += notify(db, recipients(db, balance.location_id, SUPERVISOR, MANAGER), "low_stock",
                          f"Low stock: {item.name} ({balance.qty} left, minimum {minimum})",
                          key=f"low:{item.id}:{balance.location_id}:{now.date().isoformat()}", priority="high",
                          location_id=balance.location_id, link="/inventory")
    return created


def daily_summary(db: Session, location: Location, now: datetime) -> int:
    """One pending-activities digest per location per local day, sent after 08:00 local time."""
    tz = location.timezone
    day = timeutil.local_date(now, tz)
    if now < timeutil.local_to_utc(day, SUMMARY_HOUR, tz) or is_closed(db, location.id, day):
        return 0
    items = summary.pending_items(db, {location.id}, now)
    if not items:
        return 0
    counts = summary.grouped(items)["by_urgency"]
    parts = [f"{counts[u]} {label}" for u, label in (("critical", "critical"), ("high", "high priority"), ("normal", "other")) if counts[u]]
    shown = [f"{'!! ' if i['urgency'] == 'critical' else '! ' if i['urgency'] == 'high' else ''}{i['description']} ({i['responsible']})" for i in items[:4]]
    more = len(items) - len(shown)
    body = "\n".join(shown + ([f"and {more} more"] if more > 0 else []))
    return notify(db, recipients(db, location.id, SUPERVISOR, MANAGER), "daily_summary",
                  f"{location.name} - pending: {', '.join(parts)}", body=body,
                  key=f"summary:{location.id}:{day}", location_id=location.id, link="/tasks")


def close_stale_alerts(db: Session, now: datetime) -> int:
    """Closes open alerts whose cause is gone: a check, point or place turned off, or a checkout that has since happened."""
    live_equipment = set(db.scalars(select(Equipment.id).join(Location, Location.id == Equipment.location_id).where(
        Equipment.active.is_(True), Location.active.is_(True))))
    live_schedules = set(db.scalars(select(EquipmentSchedule.id).where(EquipmentSchedule.active.is_(True),
                                                                      EquipmentSchedule.equipment_id.in_(live_equipment or {0}))))
    still_open = set(db.scalars(select(AttendanceRecord.id).where(AttendanceRecord.open_flag == 1)))
    closed = 0
    for n in db.scalars(select(Notification).where(Notification.resolved_at.is_(None), Notification.kind.in_(
            ("monitoring_due", "monitoring_overdue", "retest_due", "monitoring_escalated", "time_out_missing", "missed_checkout")))):
        prefix, _, rest = n.dedupe_key.partition(":")
        ident = rest.partition(":")[0]
        if not ident.isdigit():
            continue
        number = int(ident)
        if prefix in ("checkdue", "checkover"):
            gone = number not in live_schedules
        elif prefix in ("retest", "check_esc"):
            equipment_id = db.scalar(select(TemperatureReading.equipment_id).join(CorrectiveAction, CorrectiveAction.reading_id == TemperatureReading.id)
                                     .where(CorrectiveAction.id == number))
            gone = equipment_id not in live_equipment
        elif prefix == "pending_out":
            equipment_id = db.scalar(select(TemperatureReading.equipment_id).where(TemperatureReading.id == number))
            gone = equipment_id not in live_equipment
        elif prefix == "missedout":
            gone = number not in still_open
        else:
            continue
        if gone:
            n.resolved_at = now
            n.read_at = n.read_at or now
            closed += 1
    return closed


def round_reminders(db: Session, now: datetime) -> int:
    """From the deadline of a count round, a daily reminder for every location that has not finished counting."""
    created = 0
    for round_ in db.scalars(select(CountRound).where(CountRound.status == "counting", CountRound.deadline.is_not(None))):
        for rc in db.scalars(select(RoundCount).where(RoundCount.round_id == round_.id, RoundCount.status != "done")):
            place = db.get(Location, rc.location_id)
            today = timeutil.local_date(now, place.timezone)  # the deadline is a date at each place
            if today < round_.deadline:
                continue
            created += notify(db, recipients(db, rc.location_id, SUPERVISOR, MANAGER), "round_overdue",
                              f"Stock count not finished at {place.name} (round '{round_.name}', due {round_.deadline:%d %b})",
                              key=f"roundlate:{round_.id}:{rc.location_id}:{today}", priority="high", location_id=rc.location_id,
                              link="/stock-movements?tab=rounds")
    return created


def run_alerts(db: Session, now: datetime) -> dict[str, int]:
    totals = {"checkins": 0, "checklists": 0, "monitoring": 0, "summary": 0}
    for location in db.scalars(select(Location).where(Location.active.is_(True))):
        totals["checkins"] += missing_checkins(db, location, now)
        totals["checklists"] += checklist_alerts(db, location, now)
        totals["monitoring"] += monitoring_alerts(db, location, now)
        totals["summary"] += daily_summary(db, location, now)
    totals["checkouts"] = missed_checkouts(db, now)
    totals["corrective"] = corrective_alerts(db, now)
    totals["low_stock"] = low_stock(db, now)
    totals["closed"] = close_stale_alerts(db, now)
    totals["rounds"] = round_reminders(db, now)
    totals["pending_time_outs"] = pending_time_outs(db, now)
    return totals
