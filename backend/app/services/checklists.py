from datetime import date, datetime, time, timedelta

from sqlalchemy import delete, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import timeutil
from ..models import ChecklistInstance, ChecklistTask, ChecklistTemplate, ClosedDay, Location, Shift, TaskAssignment, TaskCompletion
from .settings import get_setting

OPEN = ("not_started", "in_progress")
DONE = ("completed", "pending_verification", "verified", "waived")


def overdue_after(db: Session, now: datetime | None = None) -> datetime:
    """The moment to measure deadlines against: a task counts as overdue only once its grace period has also passed."""
    return (now or timeutil.utc_now()) - timedelta(minutes=get_setting(db, "checklist.grace_minutes"))


PRIORITY_RANK = {"normal": 0, "low": 0, "high": 1, "critical": 2}


def alerts_for(db: Session, priority: str | None) -> bool:
    """Whether a task of this priority sends overdue alerts (Settings > Approvals and escalation); it always shows on screen."""
    return PRIORITY_RANK.get(priority or "normal", 0) >= get_setting(db, "checklist.alert_priority")


def is_closed(db: Session, location_id: int, day: date) -> bool:
    """Whether the location is marked closed that day (or every location is), so nothing is expected of it."""
    return db.scalar(select(ClosedDay.id).where(ClosedDay.start_date <= day, ClosedDay.end_date >= day,
                                                or_(ClosedDay.location_id.is_(None), ClosedDay.location_id == location_id)).limit(1)) is not None


def effective_status(inst: ChecklistInstance, now: datetime) -> str:
    if inst.status in OPEN and inst.due_at and inst.due_at < now:
        return "overdue"
    return inst.status


def _due_at(task: ChecklistTask, shift: Shift | None, day, tz: str) -> datetime:
    if task.deadline_time:
        return timeutil.local_to_utc(day, task.deadline_time, tz)
    if shift:
        return timeutil.shift_end_utc(day, shift.start_time, shift.end_time, tz)
    return timeutil.local_to_utc(day, time(23, 59), tz)


def generate_for_location(db: Session, location: Location, now: datetime) -> int:
    """Creates today's instances (location-local date); safe to run repeatedly."""
    tz = location.timezone
    today = timeutil.local_date(now, tz)
    if is_closed(db, location.id, today):
        return 0
    weekday = str(today.weekday())
    shifts = {s.id: s for s in db.scalars(select(Shift).where(Shift.active.is_(True), Shift.kind == "work"))}
    rows = db.execute(
        select(ChecklistTask, ChecklistTemplate)
        .join(ChecklistTemplate, ChecklistTask.template_id == ChecklistTemplate.id)
        .where(ChecklistTemplate.location_id == location.id, ChecklistTemplate.active.is_(True),
               ChecklistTask.active.is_(True))
    ).all()
    created = 0
    for task, template in rows:
        if (task.active_from and today < task.active_from) or (task.active_to and today > task.active_to):
            continue
        if weekday not in task.weekdays.split(","):
            continue
        targets = [task.shift_id or 0]
        if template.frequency == "per_shift" and not task.shift_id:
            targets = list(shifts)
        for shift_key in targets:
            exists = db.scalar(select(ChecklistInstance.id).where(
                ChecklistInstance.task_id == task.id, ChecklistInstance.local_date == today,
                ChecklistInstance.shift_key == shift_key))
            if exists:
                continue
            try:
                with db.begin_nested():
                    db.add(ChecklistInstance(
                        task_id=task.id, location_id=location.id, local_date=today, shift_key=shift_key,
                        due_at=_due_at(task, shifts.get(shift_key), today, tz),
                        assigned_employee_id=task.assigned_employee_id))
                created += 1
            except IntegrityError:
                continue
    return created


def mark_overdue(db: Session, now: datetime) -> int:
    result = db.execute(update(ChecklistInstance)
                        .where(ChecklistInstance.status.in_(OPEN), ChecklistInstance.due_at < overdue_after(db, now))
                        .values(status="overdue"))
    return result.rowcount


def drop_untouched_instances(db: Session, task_ids: list[int], since: date) -> bool:
    """Removes the instances the scheduler made for these tasks when nobody ever worked on them, so a checklist made in error can be deleted.

    Returns False and removes nothing when any instance was started, completed, verified or waived, or when one from before `since`
    went untouched: a checklist ignored for days is a record of work not done, not a mistake.
    """
    if not task_ids:
        return True
    mine = select(ChecklistInstance.id).where(ChecklistInstance.task_id.in_(task_ids))
    worked_on = db.scalar(select(ChecklistInstance.id).where(
        ChecklistInstance.task_id.in_(task_ids),
        or_(ChecklistInstance.status.not_in(("not_started", "overdue")), ChecklistInstance.completed_at.is_not(None),
            ChecklistInstance.local_date < since)).limit(1))
    if worked_on or db.scalar(select(TaskCompletion.id).where(TaskCompletion.instance_id.in_(mine)).limit(1)):
        return False
    db.execute(delete(TaskAssignment).where(TaskAssignment.instance_id.in_(mine)))
    db.execute(delete(ChecklistInstance).where(ChecklistInstance.task_id.in_(task_ids)))
    return True
