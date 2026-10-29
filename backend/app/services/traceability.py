import re
from collections import deque
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import timeutil
from ..models import Lot, LotLink, ReadingLot, Setting, ShelfLifeRule

GROUPS = {"poultry": ("Poultry", "POU"), "red_meat": ("Red meat", "RED"), "seafood": ("Seafood", "SEA"),
          "dairy": ("Dairy", "DAI"), "eggs": ("Eggs", "EGG"), "other": ("Other", "OTH")}
CONDITIONS = {"chilled_raw": "Chilled, raw", "vacuum_chilled": "Vacuum packed, chilled", "frozen": "Frozen",
              "thawed": "Thawed", "cooked_chilled": "Cooked, chilled"}
STATUSES = ("active", "used_up", "discarded", "on_hold")
COLD_CHAIN_KEY = "lot.cold_chain"
COLD_CHAIN_DEFAULTS = {"chilled_raw": 5.0, "vacuum_chilled": 5.0, "frozen": -12.0}


class LotError(Exception):
    """A lot cannot be made or used as asked; the message says why in words for the person."""


def shelf_hours(db: Session, group: str, condition: str) -> int | None:
    return db.scalar(select(ShelfLifeRule.hours).where(ShelfLifeRule.food_group == group, ShelfLifeRule.condition == condition))


# Units that can be compared with each other: (what they measure, size in the smallest unit).
UNITS = {"kg": ("mass", 1000), "g": ("mass", 1), "l": ("volume", 1000), "ml": ("volume", 1)}


def _measure(qty: Decimal | None, unit: str | None) -> tuple[str, Decimal] | None:
    name = (unit or "").strip().lower()
    if qty is None or not name:
        return None
    kind, size = UNITS.get(name, (name, 1))
    return kind, Decimal(qty) * size


def balance(db: Session, lot: Lot) -> dict | None:
    """What is left to portion from a lot that has a quantity and unit; only portions in a comparable unit are counted."""
    whole = _measure(lot.qty, lot.unit)
    if whole is None:
        return None
    size = UNITS.get(lot.unit.strip().lower(), (None, 1))[1]
    used, lost, unmeasured = Decimal(0), Decimal(0), 0
    for child in db.scalars(select(Lot).join(LotLink, LotLink.child_id == Lot.id).where(LotLink.parent_id == lot.id)):
        measured = _measure(child.qty, child.unit)
        if measured and measured[0] == whole[0]:
            used += measured[1]
            wasted = _measure(child.waste_qty, child.unit)
            lost += wasted[1] if wasted else 0
        else:
            unmeasured += 1
    return {"qty": float(lot.qty), "unit": lot.unit, "portioned": round(float(used / size), 2), "waste": round(float(lost / size), 2),
            "left": round(float((whole[1] - used - lost) / size), 2), "unmeasured": unmeasured}


def cold_chain_limits(db: Session) -> dict[str, float]:
    """The warmest arrival temperature in C accepted for each way food arrives; a manager can change them."""
    row = db.get(Setting, COLD_CHAIN_KEY)
    return {**COLD_CHAIN_DEFAULTS, **(row.value["v"] if row else {})}


def use_by_for(db: Session, group: str, condition: str, start: datetime, expiry_on: date | None, tz: str, rule_required: bool) -> datetime | None:
    """The earlier of the supplier's expiry (end of that day) and the shelf-life rule counted from `start`."""
    hours = shelf_hours(db, group, condition)
    if hours is None and rule_required:
        raise LotError(f"No shelf-life rule for {GROUPS[group][0]} ({CONDITIONS[condition]}). A manager sets it under Food Traceability > Shelf life")
    options = []
    if hours is not None:
        options.append(start + timedelta(hours=hours))
    if expiry_on:
        options.append(timeutil.local_to_utc(expiry_on + timedelta(days=1), time(0), tz))
    return min(options) if options else None


def _taken(db: Session, code: str) -> bool:
    return db.scalar(select(Lot.id).where(Lot.code == code)) is not None


def lot_code(supplier_lot: str) -> str:
    """The lot code a supplier's lot number gives: upper case with spaces as hyphens."""
    return re.sub(r"\s+", "-", supplier_lot.strip().upper())


def received_code(db: Session, supplier_lot: str) -> str:
    """The supplier's lot number as the code; a repeat delivery of the same number gets -B, -C and so on."""
    base = lot_code(supplier_lot)
    code, repeat = base, 1
    while _taken(db, code):
        repeat += 1
        code = f"{base}-{chr(64 + repeat) if repeat <= 26 else repeat}"
    return code


def child_code(db: Session, parent: Lot) -> str:
    """The parent's code with a running number, so the family is visible on the label."""
    number = (db.scalar(select(func.count()).select_from(LotLink).where(LotLink.parent_id == parent.id)) or 0) + 1
    while _taken(db, f"{parent.code}-{number}"):
        number += 1
    return f"{parent.code}-{number}"


def _walk(db: Session, start: int, towards_parents: bool) -> list[Lot]:
    seen: dict[int, Lot] = {}
    queue = deque([start])
    while queue:
        current = queue.popleft()
        column, other = (LotLink.child_id, LotLink.parent_id) if towards_parents else (LotLink.parent_id, LotLink.child_id)
        for lot in db.scalars(select(Lot).join(LotLink, other == Lot.id).where(column == current).order_by(Lot.id)):
            if lot.id not in seen:
                seen[lot.id] = lot
                queue.append(lot.id)
    return list(seen.values())


def ancestors(db: Session, lot_id: int) -> list[Lot]:
    """Every lot this one came from, oldest first."""
    return sorted(_walk(db, lot_id, True), key=lambda lot: lot.id)


def descendants(db: Session, lot_id: int) -> list[Lot]:
    """Every lot made from this one, however many splits away."""
    return sorted(_walk(db, lot_id, False), key=lambda lot: lot.id)


def readings_of(db: Session, lot_ids: list[int]) -> dict[int, list[int]]:
    """Reading ids per lot, for the checks (cooking, chilling) that named the lot."""
    out: dict[int, list[int]] = {i: [] for i in lot_ids}
    for lot_id, reading_id in db.execute(select(ReadingLot.lot_id, ReadingLot.reading_id).where(ReadingLot.lot_id.in_(lot_ids))):
        out[lot_id].append(reading_id)
    return out


def usable(lot: Lot, now: datetime) -> str | None:
    """Why a lot may not go into a check or a split, or None when it may."""
    if lot.status == "on_hold":
        return f"{lot.code} is on hold"
    if lot.status != "active":
        return f"{lot.code} is {lot.status.replace('_', ' ')}"
    if lot.use_by and lot.use_by < now:
        return f"{lot.code} is past its use-by date"
    return None
