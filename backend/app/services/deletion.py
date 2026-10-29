from fastapi import HTTPException, status
from sqlalchemy import delete, exists, select
from sqlalchemy.orm import Session

from ..db import Base

USED_BY = {
    "employee_location": "people assigned to it", "shift_assignment": "roster assignments", "attendance_record": "attendance records",
    "absence_record": "absence records", "inventory_balance": "stock balances", "inventory_level": "stock levels",
    "stock_transaction": "stock movements", "stock_snapshot": "stock records", "inventory_count": "stock counts",
    "inventory_transfer": "transfers", "inventory_transfer_line": "transfers", "tracked_asset": "tracked assets", "receipt": "receipts",
    "receipt_line": "receipts", "breakage_incident": "breakage reports", "notification": "alerts", "label_printer": "label printers",
    "checklist_template": "checklists", "checklist_task": "checklist tasks", "checklist_instance": "checklist records",
    "equipment": "monitoring points", "equipment_schedule": "monitoring checks", "temperature_reading": "monitoring readings",
    "lot": "food lots", "inventory_item": "items", "inventory_count_line": "stock counts",
    "employee": "people who report to them", "audit_log": "history in the audit log", "task_completion": "completed tasks",
    "task_assignment": "task assignments", "face_challenge": "face checks", "attendance_correction": "attendance corrections",
    "approval_record": "approvals", "corrective_action": "corrective actions", "lot_event": "food lot history",
}


def blockers(db: Session, record, ignore: frozenset[str] = frozenset()) -> list[str]:
    """What still holds rows that point at this record, in words a manager knows."""
    table = record.__table__
    key = next(iter(table.primary_key.columns))
    value = getattr(record, key.key)
    used: list[str] = []
    for other in Base.metadata.tables.values():
        if other.name in ignore:
            continue
        for fk in other.foreign_keys:
            if fk.column.table is table and fk.column.name == key.name and db.scalar(select(exists().where(fk.parent == value))):
                used.append(USED_BY.get(other.name, other.name.replace("_", " ")))
                break
    return list(dict.fromkeys(used))


def delete_if_unused(db: Session, record, noun: str, cascade: frozenset[str] = frozenset()) -> None:
    """Deletes the record, or refuses and names what uses it; rows in `cascade` tables are configuration that goes with it."""
    used = blockers(db, record, cascade)
    if used:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{noun} is used by {', '.join(used)}; make it inactive instead")
    table = record.__table__
    key = next(iter(table.primary_key.columns))
    for other in Base.metadata.tables.values():
        if other.name in cascade:
            for fk in other.foreign_keys:
                if fk.column.table is table:
                    db.execute(delete(other).where(fk.parent == getattr(record, key.key)))
    db.delete(record)
