from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import timeutil
from ..audit import audit
from ..services.deletion import delete_if_unused
from ..db import get_db
from ..deps import check_location, current_user, permissions_of, require, scoped_locations
from ..models import (Employee, Equipment, FoodItem, Location, Lot, LotEvent, LotLink, PortionName, ReadingLot, Setting, ShelfLifeRule, Supplier,
                      TemperatureReading, User)
from ..pagination import iso, paginate
from ..services import exporters, labels
from ..services.monitoring import describe
from ..services.organization import report_identity, stamp
from ..services.traceability import (COLD_CHAIN_KEY, CONDITIONS, GROUPS, STATUSES, LotError, ancestors, balance, child_code, cold_chain_limits,
                                     descendants, lot_code, received_code, usable, use_by_for)

router = APIRouter(prefix="/api/lots", tags=["food traceability"])

Received = Literal["chilled_raw", "vacuum_chilled", "frozen"]
Group = Literal["poultry", "red_meat", "seafood", "dairy", "eggs", "other"]


def any_of(*needed: str):
    """Dependency: 403 unless the user's role grants at least one of the permissions."""

    def dep(user: User = Depends(current_user)) -> User:
        if not set(needed) & permissions_of(user):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Permission denied")
        return user

    return dep


def _clean(value: str | None) -> str | None:
    value = " ".join((value or "").split())
    return value or None


class ReceiveIn(BaseModel):
    food_item_id: int
    location_id: int
    condition: Received
    supplier_id: int
    supplier_lot: str = Field(min_length=1, max_length=30, pattern=r"^[A-Za-z0-9][A-Za-z0-9 ._/-]*$")
    produced_on: date | None = None
    expiry_on: date | None = None
    temp_c: Decimal | None = Field(default=None, ge=-60, le=80)
    qty: Decimal | None = Field(default=None, ge=0, le=1000000)
    unit: str | None = Field(default=None, max_length=20)
    pack_count: int | None = Field(default=None, ge=1, le=10000)
    tag_number: str | None = Field(default=None, max_length=60)
    note: str | None = Field(default=None, max_length=500)

    @field_validator("supplier_lot", mode="before")
    @classmethod
    def _tidy_lot(cls, value):
        return " ".join(value.split()) if isinstance(value, str) else value

    @model_validator(mode="after")
    def _dates(self):
        if self.produced_on and self.expiry_on and self.expiry_on < self.produced_on:
            raise ValueError("The expiry date cannot be before the production date")
        return self


class PartIn(BaseModel):
    description: str = Field(min_length=2, max_length=120)
    count: int = Field(ge=1, le=1000)
    condition: Literal["chilled_raw", "vacuum_chilled", "frozen", "thawed"]
    size: Decimal | None = Field(default=None, gt=0, le=1000000)
    qty: Decimal | None = Field(default=None, ge=0, le=1000000)
    unit: str | None = Field(default=None, max_length=20)
    waste: Decimal | None = Field(default=None, ge=0, le=1000000)
    use_by: datetime | None = None

    @model_validator(mode="after")
    def _measured(self):
        if (self.size is not None or self.waste is not None) and not (self.unit or "").strip():
            raise ValueError("Give the unit of the portion size and waste")
        return self

    @field_validator("description")
    @classmethod
    def _tidy(cls, value: str) -> str:
        return " ".join(value.split())


class SplitIn(BaseModel):
    parts: list[PartIn] = Field(min_length=1, max_length=30)
    finish_parent: bool = False


class StatusIn(BaseModel):
    status: Literal["active", "used_up", "discarded", "on_hold"]
    note: str | None = Field(default=None, max_length=300)


class RuleIn(BaseModel):
    food_group: Group
    condition: Literal["chilled_raw", "vacuum_chilled", "frozen", "thawed", "cooked_chilled"]
    hours: int = Field(ge=1, le=8760)
    note: str | None = Field(default=None, max_length=300)


class ColdChainIn(BaseModel):
    condition: Received
    max_c: Decimal = Field(ge=-60, le=30)


class FoodItemIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    food_group: Group


class PortionNameIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    food_item_id: int | None = None


class PortionNameUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    food_item_id: int | None = None
    active: bool | None = None


class FoodItemUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    food_group: Group | None = None
    active: bool | None = None


def _maps(db: Session) -> dict:
    return {"item": dict(db.execute(select(FoodItem.id, FoodItem.name)).all()), "supplier": dict(db.execute(select(Supplier.id, Supplier.name)).all()),
            "location": dict(db.execute(select(Location.id, Location.name)).all()), "tz": dict(db.execute(select(Location.id, Location.timezone)).all()),
            "user": dict(db.execute(select(Employee.user_id, Employee.full_name)).all())}


def _local(moment: datetime | None, tz: str) -> str:
    return timeutil.to_local(moment, tz).strftime("%d %b %Y %H:%M") if moment else ""


def _day(value: date | None) -> str:
    return value.strftime("%d %b %Y") if value else ""


def _lot(lot: Lot, maps: dict, now: datetime) -> dict:
    return {"id": lot.id, "code": lot.code, "kind": lot.kind, "food_item_id": lot.food_item_id, "item": maps["item"].get(lot.food_item_id),
            "food_group": lot.food_group, "group_label": GROUPS[lot.food_group][0], "condition": lot.condition,
            "condition_label": CONDITIONS[lot.condition], "supplier_id": lot.supplier_id, "supplier": maps["supplier"].get(lot.supplier_id),
            "supplier_lot": lot.supplier_lot, "produced_on": lot.produced_on.isoformat() if lot.produced_on else None,
            "expiry_on": lot.expiry_on.isoformat() if lot.expiry_on else None, "use_by": iso(lot.use_by),
            "past_use_by": bool(lot.use_by and lot.use_by < now), "temp_c": float(lot.temp_c) if lot.temp_c is not None else None,
            "qty": float(lot.qty) if lot.qty is not None else None, "unit": lot.unit, "waste_qty": float(lot.waste_qty) if lot.waste_qty is not None else None,
            "pack_count": lot.pack_count,
            "pack_description": lot.pack_description, "tag_number": lot.tag_number, "location_id": lot.location_id,
            "location": maps["location"].get(lot.location_id), "status": lot.status, "note": lot.note,
            "created_by_name": maps["user"].get(lot.created_by), "created_at": iso(lot.created_at), "thawed_at": iso(lot.thawed_at)}


def _scoped(stmt, user: User, db: Session):
    allowed = scoped_locations(user, db)
    return stmt if allowed is None else stmt.where(Lot.location_id.in_(allowed))


def _get(db: Session, user: User, lot_id: int) -> Lot:
    lot = db.get(Lot, lot_id)
    if not lot:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lot not found")
    check_location(user, db, lot.location_id)
    return lot


def _initials(name: str | None) -> str:
    return "".join(part[0] for part in (name or "").split()[:2]).upper()


def _plain(qty: Decimal) -> str:
    """A quantity without trailing zeros: 6.70 as 6.7 and 2600.00 as 2600."""
    return f"{qty.normalize():f}"


def _in_all(qty: Decimal | None, unit: str | None) -> str:
    """An amount in the unit that reads best, 4800 g as 4.8 kg."""
    if qty is None:
        return ""
    name = (unit or "").strip().lower()
    if name in ("g", "ml") and qty >= 1000:
        return f"{_plain(qty / 1000)} {'kg' if name == 'g' else 'l'}"
    return f"{_plain(qty)} {unit or ''}".strip()


def _label(lot: Lot, maps: dict, style: str = "container") -> dict:
    tz = maps["tz"][lot.location_id]
    portion = lot.kind == "portion"
    amount = " ".join(part for part in (_plain(lot.qty) if lot.qty is not None else "", lot.unit or "") if part)
    if portion and style == "pack":
        detail = lot.pack_description or ""
    elif portion:
        detail = f"{lot.pack_count} x {lot.pack_description}" if lot.pack_count and lot.pack_description else (lot.pack_description or "")
        if lot.pack_count and lot.pack_description and lot.qty is not None:
            detail += f", {_in_all(lot.qty, lot.unit)} in all"
    else:
        detail = ", ".join(part for part in (amount, f"tag {lot.tag_number}" if lot.tag_number else "") if part)
    return {"code": lot.code, "item": maps["item"].get(lot.food_item_id) or "", "detail": detail, "condition": CONDITIONS[lot.condition],
            "supplier": maps["supplier"].get(lot.supplier_id) or "", "supplier_lot": lot.supplier_lot or "", "produced": _day(lot.produced_on),
            "expiry": _day(lot.expiry_on), "stamp_label": "Thawed" if lot.thawed_at else "Portioned" if portion else "Received",
            "stamped": _local(lot.thawed_at or lot.created_at, tz), "by": _initials(maps["user"].get(lot.thawed_by or lot.created_by)), "use_by": _local(lot.use_by, tz), "location": maps["location"].get(lot.location_id) or ""}


@router.get("/rules")
def list_rules(user: User = Depends(any_of("lot.view", "lot.receive", "lot.split", "lot.manage")), db: Session = Depends(get_db)):
    rules = db.scalars(select(ShelfLifeRule).order_by(ShelfLifeRule.food_group, ShelfLifeRule.condition))
    return {"groups": [{"key": k, "label": v[0]} for k, v in GROUPS.items()], "conditions": [{"key": k, "label": v} for k, v in CONDITIONS.items()],
            "rules": [{"id": r.id, "food_group": r.food_group, "condition": r.condition, "hours": r.hours, "note": r.note} for r in rules],
            "cold_chain": cold_chain_limits(db)}


@router.put("/cold-chain")
def save_cold_chain(body: ColdChainIn, user: User = Depends(require("lot.manage")), db: Session = Depends(get_db)):
    """The warmest arrival temperature a delivery may have before it is held; applies to deliveries received from now on."""
    before = cold_chain_limits(db)
    limits = {**before, body.condition: float(body.max_c)}
    row = db.get(Setting, COLD_CHAIN_KEY)
    if row:
        row.value = {"v": limits}
    else:
        db.add(Setting(key=COLD_CHAIN_KEY, value={"v": limits}))
    db.flush()
    audit(db, user, "lot.cold_chain_save", "setting", None, {body.condition: before[body.condition]}, {body.condition: limits[body.condition]})
    db.commit()
    return {"cold_chain": limits}


@router.put("/rules")
def save_rule(body: RuleIn, user: User = Depends(require("lot.manage")), db: Session = Depends(get_db)):
    rule = db.scalar(select(ShelfLifeRule).where(ShelfLifeRule.food_group == body.food_group, ShelfLifeRule.condition == body.condition))
    before = rule.hours if rule else None
    if rule:
        rule.hours, rule.note = body.hours, _clean(body.note)
    else:
        rule = ShelfLifeRule(food_group=body.food_group, condition=body.condition, hours=body.hours, note=_clean(body.note))
        db.add(rule)
    db.flush()
    audit(db, user, "lot.rule_save", "shelf_life_rule", rule.id, {"hours": before}, {"group": body.food_group, "condition": body.condition, "hours": body.hours})
    db.commit()
    return {"id": rule.id, "food_group": rule.food_group, "condition": rule.condition, "hours": rule.hours, "note": rule.note}


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: int, user: User = Depends(require("lot.manage")), db: Session = Depends(get_db)):
    rule = db.get(ShelfLifeRule, rule_id)
    if not rule:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rule not found")
    audit(db, user, "lot.rule_delete", "shelf_life_rule", rule.id, {"group": rule.food_group, "condition": rule.condition, "hours": rule.hours}, None)
    db.delete(rule)
    db.commit()
    return {"deleted": rule_id}


@router.get("/suppliers")
def list_suppliers(user: User = Depends(any_of("lot.view", "lot.receive", "lot.manage")), db: Session = Depends(get_db)):
    """Active suppliers, so receiving does not depend on a stock permission."""
    return [{"id": s.id, "name": s.name} for s in db.scalars(select(Supplier).where(Supplier.active.is_(True)).order_by(Supplier.name))]


def _item_dict(item: FoodItem) -> dict:
    return {"id": item.id, "name": item.name, "food_group": item.food_group, "group_label": GROUPS[item.food_group][0], "active": item.active}


@router.get("/food-items")
def list_food_items(include_inactive: bool = False, user: User = Depends(any_of("lot.view", "lot.receive", "lot.split", "lot.manage")),
                    db: Session = Depends(get_db)):
    stmt = select(FoodItem).order_by(FoodItem.name)
    if not include_inactive:
        stmt = stmt.where(FoodItem.active.is_(True))
    return [_item_dict(i) for i in db.scalars(stmt)]


def _name_free(db: Session, name: str, exclude: int | None = None) -> bool:
    return db.scalar(select(FoodItem.id).where(FoodItem.name.ilike(name), FoodItem.id != (exclude or 0))) is None


@router.post("/food-items", status_code=201)
def create_food_item(body: FoodItemIn, user: User = Depends(require("lot.manage")), db: Session = Depends(get_db)):
    name = " ".join(body.name.split())
    if not _name_free(db, name):
        raise HTTPException(status.HTTP_409_CONFLICT, "A food item with that name already exists")
    item = FoodItem(name=name, food_group=body.food_group)
    db.add(item)
    db.flush()
    audit(db, user, "lot.food_item_create", "food_item", item.id, None, {"name": name, "food_group": body.food_group})
    db.commit()
    return _item_dict(item)


@router.put("/food-items/{item_id}")
def update_food_item(item_id: int, body: FoodItemUpdate, user: User = Depends(require("lot.manage")), db: Session = Depends(get_db)):
    item = db.get(FoodItem, item_id)
    if not item:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Food item not found")
    data = body.model_dump(exclude_unset=True)
    if "name" in data:
        data["name"] = " ".join(data["name"].split())
        if not _name_free(db, data["name"], item.id):
            raise HTTPException(status.HTTP_409_CONFLICT, "A food item with that name already exists")
    for key, value in data.items():
        setattr(item, key, value)
    audit(db, user, "lot.food_item_update", "food_item", item.id, None, data)
    db.commit()
    return _item_dict(item)


def _portion_dict(portion: PortionName, items: dict[int, str]) -> dict:
    return {"id": portion.id, "name": portion.name, "food_item_id": portion.food_item_id, "food_item": items.get(portion.food_item_id), "active": portion.active}


def _portion_taken(db: Session, name: str, exclude: int | None = None) -> bool:
    return db.scalar(select(PortionName.id).where(func.lower(PortionName.name) == name.lower(), PortionName.id != (exclude or 0))) is not None


def _known_food_item(db: Session, food_item_id: int | None) -> None:
    if food_item_id is not None and not db.get(FoodItem, food_item_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown food item")


@router.get("/portion-names")
def list_portion_names(include_inactive: bool = False, user: User = Depends(any_of("lot.view", "lot.receive", "lot.split", "lot.manage")),
                       db: Session = Depends(get_db)):
    stmt = select(PortionName).order_by(PortionName.name)
    if not include_inactive:
        stmt = stmt.where(PortionName.active.is_(True))
    items = dict(db.execute(select(FoodItem.id, FoodItem.name)).all())
    return [_portion_dict(p, items) for p in db.scalars(stmt)]


@router.post("/portion-names", status_code=201)
def create_portion_name(body: PortionNameIn, user: User = Depends(require("lot.manage")), db: Session = Depends(get_db)):
    name = " ".join(body.name.split())
    if _portion_taken(db, name):
        raise HTTPException(status.HTTP_409_CONFLICT, "A portion name like that already exists")
    _known_food_item(db, body.food_item_id)
    portion = PortionName(name=name, food_item_id=body.food_item_id)
    db.add(portion)
    db.flush()
    audit(db, user, "lot.portion_name_create", "portion_name", portion.id, None, {"name": name, "food_item_id": body.food_item_id})
    db.commit()
    return _portion_dict(portion, dict(db.execute(select(FoodItem.id, FoodItem.name)).all()))


@router.put("/portion-names/{portion_id}")
def update_portion_name(portion_id: int, body: PortionNameUpdate, user: User = Depends(require("lot.manage")), db: Session = Depends(get_db)):
    portion = db.get(PortionName, portion_id)
    if not portion:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Portion name not found")
    data = body.model_dump(exclude_unset=True)
    if "name" in data:
        data["name"] = " ".join(data["name"].split())
        if _portion_taken(db, data["name"], portion.id):
            raise HTTPException(status.HTTP_409_CONFLICT, "A portion name like that already exists")
    if "food_item_id" in data:
        _known_food_item(db, data["food_item_id"])
    for key, value in data.items():
        setattr(portion, key, value)
    audit(db, user, "lot.portion_name_update", "portion_name", portion.id, None, data)
    db.commit()
    return _portion_dict(portion, dict(db.execute(select(FoodItem.id, FoodItem.name)).all()))


@router.delete("/portion-names/{portion_id}")
def delete_portion_name(portion_id: int, user: User = Depends(require("lot.manage")), db: Session = Depends(get_db)):
    portion = db.get(PortionName, portion_id)
    if not portion:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Portion name not found")
    audit(db, user, "lot.portion_name_delete", "portion_name", portion_id, {"name": portion.name}, None)
    db.delete(portion)
    db.commit()
    return {"deleted": portion_id}


@router.get("/search")
def search(q: str = Query(min_length=1, max_length=60), limit: int = Query(15, ge=1, le=50),
           user: User = Depends(any_of("lot.view", "lot.split", "temp.record")), db: Session = Depends(get_db)):
    """Active lots matching a typed code or item name, for pickers; those past their use-by are flagged."""
    like = f"%{q.strip()}%"
    stmt = _scoped(select(Lot).join(FoodItem, FoodItem.id == Lot.food_item_id).where(
        Lot.status == "active", or_(Lot.code.ilike(like), FoodItem.name.ilike(like), Lot.supplier_lot.ilike(like), Lot.pack_description.ilike(like))), user, db)
    maps, now = _maps(db), timeutil.utc_now()
    return [{"id": lot.id, "code": lot.code, "item": maps["item"].get(lot.food_item_id), "use_by": iso(lot.use_by), "past_use_by": bool(lot.use_by and lot.use_by < now),
             "condition_label": CONDITIONS[lot.condition], "location": maps["location"].get(lot.location_id), "pack": lot.pack_description, "supplier_lot": lot.supplier_lot}
            for lot in db.scalars(stmt.order_by(Lot.id.desc()).limit(limit))]


@router.get("/by-code/{code:path}")
def by_code(code: str, user: User = Depends(any_of("lot.view", "lot.split", "temp.record")), db: Session = Depends(get_db)):
    """What a scanned or typed code refers to, and whether it may be used right now."""
    lot = db.scalar(select(Lot).where(Lot.code == lot_code(code)))
    if not lot:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No lot has that code")
    check_location(user, db, lot.location_id)
    now = timeutil.utc_now()
    return {**_lot(lot, _maps(db), now), "blocked": usable(lot, now)}


MAX_LABELS = 200


def label_pages(db: Session, user: User, lot_ids: list[int], copies: int, style: str = "container") -> list[dict]:
    """The label content for each lot, repeated per copy, for lots the user may see; a pack style prints one label per pack of a portion lot."""
    maps = _maps(db)
    pages = []
    for lot_id in lot_ids:
        lot = _get(db, user, lot_id)
        each = (lot.pack_count or 1) * copies if style == "pack" and lot.kind == "portion" else copies
        if len(pages) + each > MAX_LABELS:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"At most {MAX_LABELS} labels at a time")
        pages += [_label(lot, maps, style)] * each
    return pages


@router.get("/labels")
def print_labels(ids: str = Query(max_length=600), copies: int = Query(1, ge=1, le=50), fmt: Literal["pdf", "zpl"] = "pdf",
                 style: Literal["container", "pack"] = "container",
                 dpi: int = Query(203, ge=150, le=600), user: User = Depends(any_of("lot.view", "lot.receive", "lot.split")), db: Session = Depends(get_db)):
    """75 x 50 mm labels, one per copy, as a PDF to print or as ZPL for a Zebra printer."""
    try:
        wanted = [int(part) for part in ids.split(",") if part.strip()]
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "ids must be lot numbers separated by commas") from None
    if not wanted or len(wanted) > 100:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Choose between 1 and 100 lots")
    pages = label_pages(db, user, wanted, copies, style)
    if fmt == "zpl":
        return Response(labels.labels_zpl(pages, dpi), media_type="text/plain", headers={"Content-Disposition": 'attachment; filename="lot-labels.zpl"'})
    return Response(labels.labels_pdf(pages), media_type="application/pdf", headers={"Content-Disposition": 'inline; filename="lot-labels.pdf"'})


@router.get("")
def list_lots(q: str | None = None, lot_status: str | None = Query(None, alias="status"), food_group: str | None = None,
              location_id: int | None = None, supplier_id: int | None = None, expiring_hours: int | None = Query(None, ge=1, le=8760), page: int = 1,
              size: int = 25, grouped: bool = False, user: User = Depends(require("lot.view")), db: Session = Depends(get_db)):
    stmt = _scoped(select(Lot).join(FoodItem, FoodItem.id == Lot.food_item_id), user, db)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Lot.code.ilike(like), FoodItem.name.ilike(like), Lot.supplier_lot.ilike(like), Lot.pack_description.ilike(like)))
    if lot_status in STATUSES:
        stmt = stmt.where(Lot.status == lot_status)
    if food_group in GROUPS:
        stmt = stmt.where(Lot.food_group == food_group)
    if supplier_id is not None:
        stmt = stmt.where(Lot.supplier_id == supplier_id)
    if location_id is not None:
        check_location(user, db, location_id)
        stmt = stmt.where(Lot.location_id == location_id)
    now = timeutil.utc_now()
    if expiring_hours:
        stmt = stmt.where(Lot.status == "active", Lot.use_by.is_not(None), Lot.use_by <= now + timedelta(hours=expiring_hours))
    if grouped:
        return _families(db, user, stmt, page, size, now)
    total, rows = paginate(db, stmt.order_by(Lot.id.desc()), page, size)
    maps = _maps(db)
    return {"total": total, "items": [_lot(r[0], maps, now) for r in rows]}


def _families(db: Session, user: User, matching, page: int, size: int, now: datetime) -> dict:
    """The delivery each matching lot came from, newest first, with every lot made from it nested beneath and what is left to portion."""
    parent_of: dict[int, int] = {}
    made_from: dict[int, list[int]] = {}
    for parent_id, child_id in db.execute(select(LotLink.parent_id, LotLink.child_id)):
        parent_of[child_id] = parent_id
        made_from.setdefault(parent_id, []).append(child_id)

    def top(lot_id: int) -> int:
        seen = {lot_id}
        while lot_id in parent_of and parent_of[lot_id] not in seen:
            lot_id = parent_of[lot_id]
            seen.add(lot_id)
        return lot_id

    roots = {top(lot_id) for lot_id in db.scalars(matching.with_only_columns(Lot.id))}
    visible = set(db.scalars(_scoped(select(Lot.id).where(Lot.id.in_(roots)), user, db))) if roots else set()
    ordered = sorted(visible, reverse=True)
    page_roots = ordered[(page - 1) * size: page * size]
    wanted, stack = set(), list(page_roots)
    while stack:
        lot_id = stack.pop()
        if lot_id not in wanted:
            wanted.add(lot_id)
            stack += made_from.get(lot_id, [])
    lots = {lot.id: lot for lot in db.scalars(select(Lot).where(Lot.id.in_(wanted)))} if wanted else {}
    maps = _maps(db)

    def node(lot_id: int) -> dict:
        kids = sorted(c for c in made_from.get(lot_id, []) if c in lots)
        return {**_lot(lots[lot_id], maps, now), "children": [node(c) for c in kids], "balance": balance(db, lots[lot_id]) if kids else None}

    return {"total": len(ordered), "items": [node(i) for i in page_roots if i in lots]}


@router.post("", status_code=201)
def receive_lot(body: ReceiveIn, user: User = Depends(require("lot.receive")), db: Session = Depends(get_db)):
    """A delivery line becomes a lot with its own code, the supplier's details and a use-by date."""
    check_location(user, db, body.location_id)
    item = db.get(FoodItem, body.food_item_id)
    if not item or not item.active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Choose a food item from the list")
    if not db.get(Supplier, body.supplier_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown supplier")
    tz = db.get(Location, body.location_id).timezone
    now = timeutil.utc_now()
    use_by = use_by_for(db, item.food_group, body.condition, now, body.expiry_on, tz, rule_required=False)
    if use_by is not None and use_by <= now:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This food is already past its expiry date. Reject the delivery instead of receiving it")
    limit = cold_chain_limits(db)[body.condition]
    too_warm = body.temp_c is not None and body.temp_c > Decimal(str(limit))
    lot = Lot(code=received_code(db, body.supplier_lot), kind="received", food_item_id=item.id, food_group=item.food_group,
              condition=body.condition, supplier_id=body.supplier_id, supplier_lot=_clean(body.supplier_lot), produced_on=body.produced_on,
              expiry_on=body.expiry_on, use_by=use_by, temp_c=body.temp_c, qty=body.qty, unit=_clean(body.unit), pack_count=body.pack_count,
              tag_number=_clean(body.tag_number), location_id=body.location_id, note=_clean(body.note), created_by=user.id, created_at=now)
    if too_warm:
        lot.status = "on_hold"
    db.add(lot)
    db.flush()
    if too_warm:
        db.add(LotEvent(lot_id=lot.id, kind="status", detail=f"Held on arrival: {body.temp_c:g} C is above the {limit:g} C limit for {CONDITIONS[body.condition].lower()} food",
                        user_id=user.id, at=now))
    audit(db, user, "lot.receive", "lot", lot.id, None, {"code": lot.code, "item": item.name, "supplier_lot": lot.supplier_lot})
    db.commit()
    return _lot(lot, _maps(db), now)


def _naive_utc(moment: datetime) -> datetime:
    return moment.astimezone(timezone.utc).replace(tzinfo=None) if moment.tzinfo else moment


@router.post("/{lot_id}/split", status_code=201)
def split_lot(lot_id: int, body: SplitIn, user: User = Depends(require("lot.split")), db: Session = Depends(get_db)):
    """Opening a lot into portion lots: each keeps the parent's supplier and dates, gets its own code and a use-by from the shelf-life rule."""
    parent = _get(db, user, lot_id)
    now = timeutil.utc_now()
    reason = usable(parent, now)
    if reason:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{reason}, so it cannot be split")
    tz = db.get(Location, parent.location_id).timezone
    manager = "lot.manage" in permissions_of(user)
    made = []
    for part in body.parts:
        if parent.condition == "thawed" and part.condition != "thawed":
            raise HTTPException(status.HTTP_409_CONFLICT, "Thawed food keeps only on its thawed shelf life and cannot be frozen or re-stored; portion it as thawed")
        if part.condition == "thawed" and parent.condition != "thawed":
            raise HTTPException(status.HTTP_409_CONFLICT, "Thaw the lot first, then portion it")
        try:
            use_by = use_by_for(db, parent.food_group, part.condition, now, parent.expiry_on, tz, rule_required=True)
        except LotError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
        if parent.use_by and (use_by is None or parent.use_by < use_by):
            use_by = parent.use_by
        if part.use_by:
            chosen = _naive_utc(part.use_by)
            if chosen < now:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "The use-by date is already past")
            if use_by is not None and chosen > use_by and not manager:
                raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a manager can set a use-by later than the shelf-life rule allows")
            use_by = chosen
        unit = _clean(part.unit)
        qty = part.size * part.count if part.size is not None else part.qty
        pack = f"{part.size:g} {unit} {part.description}"[:120] if part.size is not None else part.description
        child = Lot(code=child_code(db, parent), kind="portion", food_item_id=parent.food_item_id, food_group=parent.food_group, condition=part.condition,
                    supplier_id=parent.supplier_id, supplier_lot=parent.supplier_lot, produced_on=parent.produced_on, expiry_on=parent.expiry_on,
                    use_by=use_by, qty=qty, unit=unit, waste_qty=part.waste, pack_count=part.count, pack_description=pack,
                    tag_number=parent.tag_number, location_id=parent.location_id, created_by=user.id, created_at=now)
        db.add(child)
        db.flush()
        db.add(LotLink(parent_id=parent.id, child_id=child.id))
        made.append(child)
        if not _portion_taken(db, part.description):
            db.add(PortionName(name=part.description, food_item_id=parent.food_item_id))
            db.flush()
    codes = ", ".join(c.code for c in made)
    db.add(LotEvent(lot_id=parent.id, kind="split", detail=f"Split into {codes}"[:300], user_id=user.id, at=now))
    if body.finish_parent:
        parent.status = "used_up"
        db.add(LotEvent(lot_id=parent.id, kind="status", detail="Used up after splitting", user_id=user.id, at=now))
    audit(db, user, "lot.split", "lot", parent.id, None, {"parent": parent.code, "children": [c.code for c in made]})
    db.commit()
    maps = _maps(db)
    return {"parent": _lot(parent, maps, now), "lots": [_lot(c, maps, now) for c in made]}


@router.post("/{lot_id}/thaw")
def thaw_lot(lot_id: int, user: User = Depends(require("lot.split")), db: Session = Depends(get_db)):
    """A frozen lot becomes thawed once: its use-by is reset by the thawed shelf-life rule, never past the supplier's expiry."""
    lot = _get(db, user, lot_id)
    now = timeutil.utc_now()
    reason = usable(lot, now)
    if reason:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{reason}, so it cannot be thawed")
    if lot.condition != "frozen":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only a frozen lot can be thawed" if lot.condition != "thawed" else "This lot is already thawed and cannot be thawed again")
    tz = db.get(Location, lot.location_id).timezone
    try:
        use_by = use_by_for(db, lot.food_group, "thawed", now, lot.expiry_on, tz, rule_required=True)
    except LotError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    was = lot.use_by
    lot.condition, lot.thawed_at, lot.thawed_by, lot.use_by = "thawed", now, user.id, use_by
    db.add(LotEvent(lot_id=lot.id, kind="thaw", detail=f"Thawed; use by {_local(use_by, tz)}"[:300], user_id=user.id, at=now))
    audit(db, user, "lot.thaw", "lot", lot.id, {"use_by": iso(was)}, {"use_by": iso(use_by)})
    db.commit()
    return _lot(lot, _maps(db), now)


@router.post("/{lot_id}/status")
def set_status(lot_id: int, body: StatusIn, user: User = Depends(any_of("lot.split", "lot.manage")), db: Session = Depends(get_db)):
    """Used up or discarded by the butcher or a manager; hold, release and reopening are for managers."""
    lot = _get(db, user, lot_id)
    manager = "lot.manage" in permissions_of(user)
    ordinary = body.status in ("used_up", "discarded") and lot.status == "active"
    if not (manager or ordinary):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a manager can hold, release or reopen a lot")
    note = _clean(body.note)
    if body.status in ("discarded", "on_hold") and (note is None or len(note) < 3):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Say why in a few words")
    now = timeutil.utc_now()
    if body.status == lot.status:
        return _lot(lot, _maps(db), now)
    before = lot.status
    lot.status = body.status
    db.add(LotEvent(lot_id=lot.id, kind="status", detail=f"{before.replace('_', ' ')} to {body.status.replace('_', ' ')}" + (f": {note}" if note else ""),
                    user_id=user.id, at=now))
    audit(db, user, "lot.status", "lot", lot.id, {"status": before}, {"status": body.status, "note": note})
    db.commit()
    return _lot(lot, _maps(db), now)


def _uses(db: Session, lot_ids: list[int], maps: dict, codes: dict[int, str]) -> list[dict]:
    if not lot_ids:
        return []
    rows = db.execute(select(TemperatureReading, Equipment, ReadingLot.lot_id).join(ReadingLot, ReadingLot.reading_id == TemperatureReading.id)
                      .join(Equipment, Equipment.id == TemperatureReading.equipment_id).where(ReadingLot.lot_id.in_(lot_ids))
                      .order_by(TemperatureReading.recorded_at, TemperatureReading.id)).all()
    return [{"reading_id": r.id, "lot_id": lot_id, "lot_code": codes[lot_id], "at": iso(r.recorded_at), "equipment": eq.name, "stage": r.stage,
             "display": describe(r), "passed": r.passed, "by": maps["user"].get(r.recorded_by), "rejected": r.rejected_at is not None,
             "tz": maps["tz"].get(r.location_id)} for r, eq, lot_id in rows]


EVENT_TITLES = {"split": "Split", "thaw": "Thawed", "status": "Status changed"}


def _timeline(db: Session, family: list[Lot], uses: list[dict], maps: dict) -> list[dict]:
    """Everything that happened to a lot and the lots around it, oldest first."""
    items = []
    for x in family:
        if x.kind == "received":
            title = "Received"
            detail = f"{maps['item'].get(x.food_item_id)} from {maps['supplier'].get(x.supplier_id) or 'unknown supplier'}, supplier lot {x.supplier_lot or '-'}"
        else:
            title, detail = "Portioned", f"{x.pack_count} x {x.pack_description}"
            if x.qty is not None and x.unit:
                detail += f", total {float(x.qty):g} {x.unit}"
            if x.waste_qty:
                detail += f", waste {float(x.waste_qty):g} {x.unit}"
        items.append({"at": iso(x.created_at), "kind": x.kind, "title": title, "detail": detail, "lot_code": x.code, "by": maps["user"].get(x.created_by), "tone": "neutral"})
    codes = {x.id: x.code for x in family}
    for e in db.scalars(select(LotEvent).where(LotEvent.lot_id.in_(codes)).order_by(LotEvent.id)):
        items.append({"at": iso(e.at), "kind": e.kind, "title": EVENT_TITLES.get(e.kind, e.kind.capitalize()), "detail": e.detail, "lot_code": codes[e.lot_id],
                      "by": maps["user"].get(e.user_id), "tone": "neutral"})
    for u in uses:
        items.append({"at": u["at"], "kind": "check", "title": u["stage"], "detail": f"{u['equipment']}: {u['display']}" + (" (rejected)" if u["rejected"] else ""),
                      "lot_code": u["lot_code"], "by": u["by"], "tone": "neutral" if u["rejected"] else "ok" if u["passed"] else "critical"})
    return sorted(items, key=lambda i: (_moment(i["at"]), i["kind"] != "split"))


def _trace(db: Session, lot: Lot) -> dict:
    now = timeutil.utc_now()
    maps = _maps(db)
    back, forward = ancestors(db, lot.id), descendants(db, lot.id)
    codes = {x.id: x.code for x in [lot, *back, *forward]}
    uses_back, uses_forward = _uses(db, [x.id for x in back], maps, codes), _uses(db, [lot.id, *[x.id for x in forward]], maps, codes)
    return {"lot": _lot(lot, maps, now), "balance": balance(db, lot), "back": [_lot(x, maps, now) for x in back], "forward": [_lot(x, maps, now) for x in forward],
            "uses_back": uses_back, "uses_forward": uses_forward, "timeline": _timeline(db, [*back, lot, *forward], [*uses_back, *uses_forward], maps),
            "events": [{"kind": e.kind, "detail": e.detail, "by": maps["user"].get(e.user_id), "at": iso(e.at)}
                       for e in db.scalars(select(LotEvent).where(LotEvent.lot_id == lot.id).order_by(LotEvent.id))]}


@router.get("/{lot_id}")
def lot_detail(lot_id: int, user: User = Depends(require("lot.view")), db: Session = Depends(get_db)):
    """The lot, where it came from, what was made from it, the checks that used it and its history."""
    return _trace(db, _get(db, user, lot_id))


def _moment(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text.rstrip("Z")) if text else None


@router.get("/{lot_id}/trace/export")
def export_trace(lot_id: int, user: User = Depends(require("lot.view")), db: Session = Depends(get_db)):
    """A printable trace of one lot, back to the supplier and forward to every cooking record."""
    lot = _get(db, user, lot_id)
    traced = _trace(db, lot)
    identity = report_identity(db)
    now = timeutil.utc_now()
    tz = identity["timezone"]
    employee = user.employee
    zones = {i: z for i, z in db.execute(select(Location.id, Location.timezone))}

    def lot_row(x: dict) -> dict:
        zone = zones[x["location_id"]]
        return {"code": x["code"], "item": x["item"], "type": "Portions" if x["kind"] == "portion" else "Delivery", "supplier": x["supplier"] or "",
                "supplier_lot": x["supplier_lot"] or "", "produced": _day(date.fromisoformat(x["produced_on"])) if x["produced_on"] else "",
                "expiry": _day(date.fromisoformat(x["expiry_on"])) if x["expiry_on"] else "", "created": _local(_moment(x["created_at"]), zone),
                "use_by": _local(_moment(x["use_by"]), zone), "status": x["status"].replace("_", " "), "location": x["location"] or ""}

    lot_columns = [("code", "Lot"), ("item", "Item"), ("type", "Type"), ("supplier", "Supplier"), ("supplier_lot", "Supplier lot"), ("produced", "Produced"),
                   ("expiry", "Expiry"), ("created", "Received or portioned"), ("use_by", "Use by"), ("status", "Status"), ("location", "Location")]
    use_columns = [("when", "When"), ("lot", "Lot"), ("equipment", "Monitoring point"), ("stage", "Check"), ("value", "Recorded"), ("result", "Result"), ("by", "By")]

    def use_row(u: dict) -> dict:
        return {"when": _local(_moment(u["at"]), u["tz"] or tz), "lot": u["lot_code"], "equipment": u["equipment"], "stage": u["stage"],
                "value": u["display"], "result": "PASS" if u["passed"] else "FAIL", "by": u["by"] or ""}

    groups = [{"title": f"Lot {lot.code}", "meta": [], "columns": lot_columns, "rows": [lot_row(traced["lot"])], "totals": []},
              {"title": "Came from (back to the supplier)", "meta": [], "columns": lot_columns, "rows": [lot_row(x) for x in traced["back"]], "totals": [],
               "empty": "Nothing before it: this lot came straight from the supplier"},
              {"title": "Checks recorded on the lots it came from", "meta": [], "columns": use_columns, "rows": [use_row(u) for u in traced["uses_back"]], "totals": [], "empty": "No checks were recorded on those lots"},
              {"title": "Made from this lot (forward)", "meta": [], "columns": lot_columns, "rows": [lot_row(x) for x in traced["forward"]],
               "totals": [("Portion lots", str(len(traced["forward"])))], "empty": "Nothing has been made from this lot yet"},
              {"title": "Checks recorded on this lot and what was made from it, including cooking", "meta": [], "columns": use_columns,
               "rows": [use_row(u) for u in traced["uses_forward"]], "totals": [("Records", str(len(traced["uses_forward"])))],
               "empty": "No cooking or other check has used this lot yet"}]
    doc = {"title": f"Food trace - {lot.code}", "period": {"label": f"Traced {stamp(now, tz)}"}, "locations": [traced["lot"]["location"] or ""],
           "prepared_by": employee.full_name if employee else user.email, "prepared_position": employee.job_title if employee else (user.role.label or user.role.name),
           "generated_at": stamp(now, tz), "organization": identity, "groups": groups}
    audit(db, user, "lot.trace_export", "lot", lot.id, None, {"code": lot.code})
    db.commit()
    return Response(exporters.record_to_pdf(doc), media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="trace-{lot.code}.pdf"'})


@router.delete("/food-items/{item_id}")
def delete_food_item(item_id: int, user: User = Depends(require("lot.manage")), db: Session = Depends(get_db)):
    item = db.get(FoodItem, item_id)
    if not item:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Food item not found")
    before = {"name": item.name, "food_group": item.food_group}
    delete_if_unused(db, item, item.name)
    audit(db, user, "lot.food_item_delete", "food_item", item_id, before, None)
    db.commit()
    return {"deleted": item_id}
