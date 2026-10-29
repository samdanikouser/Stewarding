from sqlalchemy import select
from sqlalchemy.orm import Session

from ..cache import memo

from ..models import Setting

# Every operational threshold is configurable; these are defaults until a manager changes them.
DEFAULTS: dict[str, int | bool] = {
    "temp.due_grace_minutes": 30,
    "temp.retest_minutes": 15,
    "temp.repeat_failure_count": 3,
    "temp.repeat_failure_days": 7,
    "temp.escalate_after_minutes": 60,
    "reminder.lead_minutes": 30,
    "escalation.supervisor_after_minutes": 30,
    "escalation.manager_after_minutes": 120,
    "breakage.approval_qty": 5,
    "breakage.approval_cost": 100,
    "attendance.missed_checkout_hours": 16,
    "attendance.missed_checkout_after_shift_hours": 2,
    "attendance.max_accuracy_m": 100,
    "stock.lock_through": 0,
    "checklist.grace_minutes": 15,
    "checklist.alert_priority": 0,
    "stock.round_tolerance_units": 2,
    "stock.round_tolerance_percent": 5,
    "attendance.by_location": 1,
    "temp.pending_alert_hours": 12,
    "attendance.face_required": 0,
    "attendance.face_liveness": 1,
    "attendance.snapshot_days": 90,
    "attendance.face_match_max": 45,
    "approval.checklists": 1,
    "scan.monitoring_required": 0,
    "scan.checklists_required": 0,
    "scan.valid_minutes": 30,
    "receiving.allow_old_invoices": 0,
}

# The smallest and largest value a manager may save for each setting; an on/off setting is 0 or 1.
LIMITS: dict[str, tuple[int, int]] = {
    "temp.due_grace_minutes": (0, 240),
    "temp.retest_minutes": (0, 1440),
    "temp.repeat_failure_count": (1, 50),
    "temp.repeat_failure_days": (1, 365),
    "temp.escalate_after_minutes": (0, 10080),
    "reminder.lead_minutes": (0, 1440),
    "escalation.supervisor_after_minutes": (0, 10080),
    "escalation.manager_after_minutes": (0, 10080),
    "breakage.approval_qty": (0, 100_000),
    "breakage.approval_cost": (0, 100_000),
    "attendance.missed_checkout_hours": (1, 72),
    "attendance.missed_checkout_after_shift_hours": (0, 24),
    "attendance.max_accuracy_m": (0, 5000),
    "stock.lock_through": (0, 299912),
    "checklist.grace_minutes": (0, 240),
    "checklist.alert_priority": (0, 2),
    "stock.round_tolerance_units": (0, 1000),
    "stock.round_tolerance_percent": (0, 100),
    "attendance.by_location": (0, 1),
    "temp.pending_alert_hours": (0, 168),
    "attendance.face_required": (0, 1),
    "attendance.face_liveness": (0, 1),
    "attendance.snapshot_days": (0, 3650),
    "attendance.face_match_max": (10, 80),
    "approval.checklists": (0, 1),
    "scan.monitoring_required": (0, 1),
    "scan.checklists_required": (0, 1),
    "scan.valid_minutes": (1, 720),
    "receiving.allow_old_invoices": (0, 1),
}


def _stored(db: Session) -> dict:
    """Every stored setting, read once per transaction."""
    return memo(db, "settings", lambda: {row.key: row.value["v"] for row in db.scalars(select(Setting))})


def get_setting(db: Session, key: str):
    stored = _stored(db)
    return stored[key] if key in stored else DEFAULTS[key]


def all_settings(db: Session) -> dict:
    return {key: get_setting(db, key) for key in DEFAULTS}
