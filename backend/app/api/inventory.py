import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit import audit
from ..services.deletion import delete_if_unused
from ..services.images import thumbnail_jpeg
from ..db import get_db
from ..deps import check_location, permissions_of, require, scoped_locations
from ..models import (ItemSupplier, Employee, InventoryBalance, InventoryCategory, InventoryItem, InventoryLevel, InventoryUnit, Location,
                      Receipt, ReceiptLine, StockTransaction, Supplier, TrackedAsset, User)
from ..pagination import paginate, row
from ..services.costing import last_purchases
from ..services.history import item_history
from ..services.inventory import StockError, counts_as_received, level_map, norm, places_in, post_txn, shortage_rows, unheld_items
from .uploads import MAX_BYTES, file_kind, upload_path
from ..services.similarity import SCAN_LIMIT, compact, find_similar, token_key, tokens

router = APIRouter(prefix="/api/inventory", tags=["inventory"])

ITEM_FIELDS = ("id", "code", "name", "category_id", "unit_id", "description", "image_path",
               "storage_location", "min_level", "target_level", "opening_qty", "supplier_id", "is_tracked_asset", "active")


class CategoryIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)


class UnitIn(BaseModel):
    name: str = Field(min_length=1, max_length=30)


MAX_LEVEL = 1_000_000
MAX_UNIT_COST = Decimal("100000")


def _clean_name(value: str | None) -> str | None:
    if value is None:
        return value
    value = " ".join(value.split())
    if len(value) < 2:
        raise ValueError("Enter an item name of at least 2 characters")
    return value


class ItemIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    category_id: int
    unit_id: int
    description: str | None = Field(default=None, max_length=2000)
    storage_location: str | None = Field(default=None, max_length=80)
    min_level: int = Field(default=0, ge=0, le=MAX_LEVEL)
    target_level: int | None = Field(default=None, ge=0, le=MAX_LEVEL)
    unit_cost: Decimal | None = Field(default=None, ge=0, le=MAX_UNIT_COST)
    supplier_id: int | None = None  # the preferred supplier
    supplier_ids: list[int] = Field(default_factory=list, max_length=50)  # others it is also bought from
    is_tracked_asset: bool = False
    opening_qty: int = Field(default=0, ge=0, le=MAX_LEVEL)
    opening_location_id: int | None = None

    _name = field_validator("name")(_clean_name)

    @model_validator(mode="after")
    def _levels(self):
        if self.target_level is not None and self.target_level < self.min_level:
            raise ValueError("The target level cannot be below the minimum level")
        return self


class ItemUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    category_id: int | None = None
    unit_id: int | None = None
    description: str | None = Field(default=None, max_length=2000)
    storage_location: str | None = Field(default=None, max_length=80)
    min_level: int | None = Field(default=None, ge=0, le=MAX_LEVEL)
    target_level: int | None = Field(default=None, ge=0, le=MAX_LEVEL)
    unit_cost: Decimal | None = Field(default=None, ge=0, le=MAX_UNIT_COST)
    supplier_id: int | None = None
    supplier_ids: list[int] | None = Field(default=None, max_length=50)
    active: bool | None = None

    _name = field_validator("name")(_clean_name)


class TxnIn(BaseModel):
    item_id: int
    location_id: int
    txn_type: Literal["receipt", "issue", "return", "damage", "adjustment", "opening"]
    qty: int = Field(ge=-MAX_LEVEL, le=MAX_LEVEL)
    reason: str | None = Field(default=None, max_length=500)


class AssetIn(BaseModel):
    item_id: int
    asset_tag: str = Field(min_length=2, max_length=40)
    location_id: int
    condition: str = Field(default="good", pattern="^(good|fair|damaged|missing)$")
    custodian_employee_id: int | None = None


class AssetUpdate(BaseModel):
    location_id: int | None = None
    condition: str | None = Field(default=None, pattern="^(good|fair|damaged|missing)$")
    custodian_employee_id: int | None = None


def _can_see_cost(user: User) -> bool:
    return bool({"inventory.manage", "stock.transfer"} & permissions_of(user))


class NameUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    active: bool | None = None


@router.get("/categories")
def list_categories(include_inactive: bool = False, user: User = Depends(require("inventory.view")),
                    db: Session = Depends(get_db)):
    stmt = select(InventoryCategory).order_by(InventoryCategory.name)
    if not include_inactive:
        stmt = stmt.where(InventoryCategory.active.is_(True))
    return [row(c, "id", "name", "active") for c in db.scalars(stmt)]


def _name_taken(db: Session, model, name: str, exclude_id: int | None = None, **scope) -> bool:
    stmt = select(model).where(*(getattr(model, k) == v for k, v in scope.items()))
    return any(norm(o.name) == norm(name) and o.id != exclude_id for o in db.scalars(stmt))


@router.post("/categories", status_code=201)
def create_category(body: CategoryIn, user: User = Depends(require("inventory.manage")), db: Session = Depends(get_db)):
    if _name_taken(db, InventoryCategory, body.name):
        raise HTTPException(status.HTTP_409_CONFLICT, "Category already exists")
    category = InventoryCategory(name=" ".join(body.name.split()))
    db.add(category)
    db.flush()
    audit(db, user, "inventory.category_create", "inventory_category", category.id, None, body.model_dump())
    db.commit()
    return row(category, "id", "name", "active")


@router.put("/categories/{category_id}")
def update_category(category_id: int, body: NameUpdate, user: User = Depends(require("inventory.manage")),
                    db: Session = Depends(get_db)):
    category = db.get(InventoryCategory, category_id)
    if not category:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Category not found")
    data = body.model_dump(exclude_unset=True)
    if "name" in data and _name_taken(db, InventoryCategory, data["name"], category.id):
        raise HTTPException(status.HTTP_409_CONFLICT, "Category already exists")
    before = {k: getattr(category, k) for k in data}
    for key, value in data.items():
        setattr(category, key, " ".join(value.split()) if key == "name" else value)
    audit(db, user, "inventory.category_update", "inventory_category", category.id, before, data)
    db.commit()
    return row(category, "id", "name", "active")


@router.get("/units")
def list_units(include_inactive: bool = False, user: User = Depends(require("inventory.view")),
               db: Session = Depends(get_db)):
    stmt = select(InventoryUnit).order_by(InventoryUnit.name)
    if not include_inactive:
        stmt = stmt.where(InventoryUnit.active.is_(True))
    return [row(u, "id", "name", "active") for u in db.scalars(stmt)]


@router.post("/units", status_code=201)
def create_unit(body: UnitIn, user: User = Depends(require("inventory.manage")), db: Session = Depends(get_db)):
    if _name_taken(db, InventoryUnit, body.name):
        raise HTTPException(status.HTTP_409_CONFLICT, "Unit already exists")
    unit = InventoryUnit(name=" ".join(body.name.split()))
    db.add(unit)
    db.flush()
    audit(db, user, "inventory.unit_create", "inventory_unit", unit.id, None, {"name": body.name})
    db.commit()
    return row(unit, "id", "name", "active")


@router.put("/units/{unit_id}")
def update_unit(unit_id: int, body: NameUpdate, user: User = Depends(require("inventory.manage")),
                db: Session = Depends(get_db)):
    unit = db.get(InventoryUnit, unit_id)
    if not unit:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unit not found")
    data = body.model_dump(exclude_unset=True)
    if "name" in data and _name_taken(db, InventoryUnit, data["name"], unit.id):
        raise HTTPException(status.HTTP_409_CONFLICT, "Unit already exists")
    before = {k: getattr(unit, k) for k in data}
    for key, value in data.items():
        setattr(unit, key, " ".join(value.split()) if key == "name" else value)
    audit(db, user, "inventory.unit_update", "inventory_unit", unit.id, before, data)
    db.commit()
    return row(unit, "id", "name", "active")


def _scope(db: Session, user: User, location_id: int | None) -> set[int] | None:
    """Locations whose balances the caller may see; None means all."""
    if location_id is not None:
        check_location(user, db, location_id)
        return {location_id}
    return scoped_locations(user, db)


def _serialize_items(db: Session, user: User, items: list[InventoryItem], scope: set[int] | None) -> list[dict]:
    ids = [i.id for i in items]
    stmt = select(InventoryBalance).where(InventoryBalance.item_id.in_(ids)) if ids else None
    if stmt is not None and scope is not None:
        stmt = stmt.where(InventoryBalance.location_id.in_(scope))
    by_item: dict[int, dict[int, int]] = {}
    balances: dict[int, list[InventoryBalance]] = {}
    for bal in (db.scalars(stmt) if stmt is not None else []):
        by_item.setdefault(bal.item_id, {})[bal.location_id] = bal.qty
        balances.setdefault(bal.item_id, []).append(bal)
    received = select(StockTransaction.item_id, StockTransaction.location_id, func.sum(StockTransaction.qty_delta)).where(
        counts_as_received(), StockTransaction.item_id.in_(ids)).group_by(
        StockTransaction.item_id, StockTransaction.location_id)
    if scope is not None:
        received = received.where(StockTransaction.location_id.in_(scope))
    received_by_item: dict[int, dict[int, int]] = {}
    for item_id, location_id, total in (db.execute(received) if ids else []):
        received_by_item.setdefault(item_id, {})[location_id] = int(total)
    categories = {c.id: c.name for c in db.scalars(select(InventoryCategory))}
    units = {u.id: u.name for u in db.scalars(select(InventoryUnit))}
    suppliers = {s.id: s.name for s in db.scalars(select(Supplier))}
    others: dict[int, list[int]] = {}
    for link in db.scalars(select(ItemSupplier).where(ItemSupplier.item_id.in_(ids))) if ids else []:
        others.setdefault(link.item_id, []).append(link.supplier_id)
    levels = level_map(db)
    unheld = {i.id for i in unheld_items(db)} & set(ids)
    places = places_in(db, scope) if unheld else []
    show_cost = _can_see_cost(user)
    last = last_purchases(db, ids) if show_cost else {}
    out = []
    for item in items:
        per_location = by_item.get(item.id, {})
        qty = sum(per_location.values())
        short_at = [{"location_id": loc, "qty": have, "minimum": levels.get((item.id, loc), item.min_level)}
                    for loc, have in per_location.items() if have < levels.get((item.id, loc), item.min_level)]
        if item.id in unheld:
            short_at = [{"location_id": loc, "qty": 0, "minimum": item.min_level} for loc in places]
        single = next(iter(scope)) if scope is not None and len(scope) == 1 else None
        own = {loc: m for (i, loc), m in levels.items() if i == item.id and (scope is None or loc in scope)}
        entry = {**row(item, *ITEM_FIELDS), "category": categories.get(item.category_id), "unit": units.get(item.unit_id),
                 "supplier": suppliers.get(item.supplier_id) if show_cost else None,
                 "supplier_ids": sorted(others.get(item.id, [])) if show_cost else [],
                 "other_suppliers": [suppliers[s] for s in sorted(others.get(item.id, [])) if s in suppliers] if show_cost else [],
                 "qty": qty, "received": sum(received_by_item.get(item.id, {}).values()),
                 "received_by_location": received_by_item.get(item.id, {}), "by_location": per_location,
                 "low": bool(short_at), "short_at": short_at, "location_minimums": own,
                 "minimum": levels.get((item.id, single), item.min_level) if single is not None else item.min_level}
        if show_cost:
            entry["unit_cost"] = float(item.unit_cost) if item.unit_cost is not None else None
            held = [(b.qty, b.avg_cost if b.avg_cost is not None else item.unit_cost) for b in balances.get(item.id, [])]
            stocked = [(q, c) for q, c in held if c is not None and q > 0]
            kept = [b.avg_cost for b in balances.get(item.id, []) if b.avg_cost is not None]
            entry["avg_cost"] = round(float(sum(q * c for q, c in stocked) / sum(q for q, _ in stocked)), 3) if stocked else (float(kept[0]) if kept else None)
            purchase = last.get(item.id)
            entry["last_purchase"] = {**purchase, "supplier": suppliers.get(purchase["supplier_id"])} if purchase else None
            entry["value"] = round(sum(float(q * c) for q, c in held if c is not None), 3) if any(c is not None for _, c in held) else None
        out.append(entry)
    return out


def _history(db: Session, user: User, item_id: int, location_id: int | None, date_from: date | None, date_to: date | None) -> tuple[InventoryItem, dict]:
    item = get_item_or_404(db, item_id)
    scope = _scope(db, user, location_id)
    return item, item_history(db, item_id, scope, date_from, date_to, _can_see_cost(user))


@router.get("/items/{item_id}/history")
def item_history_page(item_id: int, location_id: int | None = None, date_from: date | None = None, date_to: date | None = None,
                      page: int = 1, size: int = 50, user: User = Depends(require("inventory.module")), db: Session = Depends(get_db)):
    """Everything that ever happened to one item: totals by kind, and the movements with a running balance."""
    item, story = _history(db, user, item_id, location_id, date_from, date_to)
    size = min(max(size, 1), 200)
    rows = story["rows"]
    unit = db.scalar(select(InventoryUnit.name).where(InventoryUnit.id == item.unit_id))
    on_hand = db.scalar(select(func.coalesce(func.sum(InventoryBalance.qty), 0)).where(InventoryBalance.item_id == item_id, *(
        [InventoryBalance.location_id.in_(_scope(db, user, location_id))] if _scope(db, user, location_id) is not None else [])))
    return {"item": {"id": item.id, "code": item.code, "name": item.name, "unit": unit}, **{k: v for k, v in story.items() if k != "rows"},
            "on_hand_now": int(on_hand), "adds_up": story["closing"] == int(on_hand) if not date_to else None,
            "total": len(rows), "rows": rows[(max(page, 1) - 1) * size: max(page, 1) * size]}


@router.get("/items/{item_id}/history.csv")
def item_history_csv(item_id: int, location_id: int | None = None, date_from: date | None = None, date_to: date | None = None,
                     user: User = Depends(require("inventory.module")), db: Session = Depends(get_db)):
    import csv
    import io
    from fastapi.responses import Response

    item, story = _history(db, user, item_id, location_id, date_from, date_to)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["When (UTC)", "Location", "What", "Quantity", "Balance", "Document", "Reason", "By"] + (["Unit cost"] if story["rows"] and "unit_cost" in story["rows"][0] else []))
    for r in reversed(story["rows"]):
        writer.writerow([r["at"], r["location"], r["label"], r["qty"], r["balance"], r["document"] or "", r["reason"] or "", r["by"] or ""] + ([r["unit_cost"]] if "unit_cost" in r else []))
    return Response("\ufeff" + out.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{item.code}-history.csv"'})


@router.get("/items/{item_id}/price-history")
def price_history(item_id: int, location_id: int | None = None, date_by: Literal["invoice", "received"] = "invoice",
                  user: User = Depends(require("inventory.view")), db: Session = Depends(get_db)):
    """What each posted invoice paid for this item, oldest first, with the change from the one before and a summary."""
    if not _can_see_cost(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Permission denied")
    item = db.get(InventoryItem, item_id)
    if not item:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")
    scope = _scope(db, user, location_id)
    stmt = (select(Receipt.id, Receipt.invoice_number, Receipt.invoice_date, Receipt.received_on, Receipt.received_at, Receipt.supplier_id,
                   ReceiptLine.qty, ReceiptLine.line_total, StockTransaction.unit_cost)
            .join(ReceiptLine, ReceiptLine.receipt_id == Receipt.id)
            .outerjoin(StockTransaction, StockTransaction.id == ReceiptLine.transaction_id)
            .where(ReceiptLine.item_id == item_id, Receipt.status == "posted", Receipt.doc_type == "receipt",
                   ReceiptLine.line_total > 0, ReceiptLine.qty > 0))
    if scope is not None:
        stmt = stmt.where(Receipt.location_id.in_(scope))
    suppliers = {s.id: s.name for s in db.scalars(select(Supplier))}
    rows = []
    for rid, number, invoiced, received_on, received_at, supplier_id, qty, total, ledger_cost in db.execute(stmt):
        day = (invoiced.date() if invoiced else received_on or received_at.date()) if date_by == "invoice" else (received_on or received_at.date())
        rows.append((day, rid, {"date": day.isoformat(), "price": float((Decimal(str(ledger_cost)) if ledger_cost is not None else Decimal(str(total)) / qty).quantize(Decimal("0.001"))), "qty": qty,
                                "supplier": suppliers.get(supplier_id), "invoice": number, "receipt_id": rid}))
    points = [p for _, _, p in sorted(rows, key=lambda r: (r[0], r[1]))]
    for before, now in zip(points, points[1:]):
        now["change_pct"] = round((now["price"] - before["price"]) / before["price"] * 100, 1)
    if points:
        points[0]["change_pct"] = None
    prices = [p["price"] for p in points]
    summary = None
    if points:
        summary = {"count": len(points), "first": prices[0], "latest": prices[-1], "lowest": min(prices), "highest": max(prices),
                   "average": round(sum(p["price"] * p["qty"] for p in points) / sum(p["qty"] for p in points), 3),
                   "change_pct": round((prices[-1] - prices[0]) / prices[0] * 100, 1) if len(points) > 1 else None}
    return {"item": {"id": item.id, "code": item.code, "name": item.name}, "date_by": date_by, "points": points, "summary": summary}


@router.get("/items")
def list_items(search: str | None = None, category_id: int | None = None, location_id: int | None = None,
               low_only: bool = False, active: bool | None = True, page: int = 1, size: int = 25,
               user: User = Depends(require("inventory.view")), db: Session = Depends(get_db)):
    scope = _scope(db, user, location_id)
    stock = select(InventoryBalance.item_id, func.sum(InventoryBalance.qty).label("qty")).group_by(InventoryBalance.item_id)
    if scope is not None:
        stock = stock.where(InventoryBalance.location_id.in_(scope))
    stock = stock.subquery()
    stmt = select(InventoryItem).outerjoin(stock, stock.c.item_id == InventoryItem.id)
    if category_id is not None:
        stmt = stmt.where(InventoryItem.category_id == category_id)
    if active is not None:
        stmt = stmt.where(InventoryItem.active.is_(active))
    if search:
        like = f"%{search.strip()}%"
        stmt = stmt.where(or_(InventoryItem.name.ilike(like), InventoryItem.code.ilike(like)))
    if low_only:
        short = (select(InventoryBalance.item_id)
                 .outerjoin(InventoryLevel, and_(InventoryLevel.item_id == InventoryBalance.item_id,
                                                 InventoryLevel.location_id == InventoryBalance.location_id))
                 .where(InventoryBalance.item_id == InventoryItem.id,
                        InventoryBalance.qty < func.coalesce(InventoryLevel.min_level, InventoryItem.min_level)))
        if scope is not None:
            short = short.where(InventoryBalance.location_id.in_(scope))
        never_held = and_(InventoryItem.active.is_(True), InventoryItem.min_level > 0,
                          ~select(InventoryBalance.item_id).where(InventoryBalance.item_id == InventoryItem.id).exists())
        stmt = stmt.where(or_(short.exists(), never_held))
    total, rows = paginate(db, stmt.order_by(InventoryItem.code), page, size)
    items = [r[0] for r in rows]
    result = {"total": total, "items": _serialize_items(db, user, items, scope)}
    if _can_see_cost(user):
        worth = (select(func.coalesce(func.sum(InventoryBalance.qty * func.coalesce(InventoryBalance.avg_cost, InventoryItem.unit_cost, 0)), 0))
                 .select_from(InventoryBalance).join(InventoryItem, InventoryItem.id == InventoryBalance.item_id))
        if scope is not None:
            worth = worth.where(InventoryBalance.location_id.in_(scope))
        result["total_value"] = round(float(db.scalar(worth)), 3)
    return result


def _check_suppliers(db: Session, ids: list[int]) -> None:
    found = set(db.scalars(select(Supplier.id).where(Supplier.id.in_(ids), Supplier.active.is_(True)))) if ids else set()
    if found != set(ids):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown or inactive supplier")


def _set_other_suppliers(db: Session, item: InventoryItem, ids: list[int]) -> None:
    """The suppliers an item is also bought from; the preferred one is not repeated here."""
    wanted = set(ids) - {item.supplier_id}
    have = {link.supplier_id: link for link in db.scalars(select(ItemSupplier).where(ItemSupplier.item_id == item.id))}
    for supplier_id, link in have.items():
        if supplier_id not in wanted:
            db.delete(link)
    for supplier_id in wanted - set(have):
        db.add(ItemSupplier(item_id=item.id, supplier_id=supplier_id))


def _check_links(db: Session, category_id: int | None, unit_id: int | None, supplier_id: int | None) -> None:
    """Category, unit and supplier must exist and be active."""
    if category_id is not None:
        category = db.get(InventoryCategory, category_id)
        if not category or not category.active:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown or inactive category")
    if unit_id is not None:
        unit = db.get(InventoryUnit, unit_id)
        if not unit or not unit.active:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown or inactive unit")
    if supplier_id is not None:
        supplier = db.get(Supplier, supplier_id)
        if not supplier or not supplier.active:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown or inactive supplier")


def _check_duplicate(db: Session, name: str, exclude_id: int | None = None) -> None:
    """One item master entry per normalised name."""
    if name is not None:
        # the same item written differently shares a compact key (spacing, punctuation) or a token key (word order, plurals)
        clash = db.execute(select(InventoryItem.code, InventoryItem.name, InventoryItem.active).where(
            InventoryItem.id != (exclude_id or 0),
            or_(InventoryItem.name_key == norm(name), InventoryItem.compact_key == compact(name),
                InventoryItem.token_key == token_key(name))).order_by(InventoryItem.id).limit(1)).first()
        if clash:
            state = "" if clash.active else " (inactive - reactivate it instead)"
            raise HTTPException(status.HTTP_409_CONFLICT, f"{clash.name} ({clash.code}) already exists{state}")


@router.get("/items/lookup")
def similar_items(q: str, user: User = Depends(require("inventory.view")), db: Session = Depends(get_db)):
    """Existing items that are the same as, or close to, the typed name, so a duplicate is noticed before it is created."""
    if len(norm(q)) < 3:
        return []
    columns = (InventoryItem.id, InventoryItem.code, InventoryItem.name, InventoryItem.active)
    stmt = select(*columns)
    if db.scalar(select(func.count()).select_from(InventoryItem)) > SCAN_LIMIT:
        # a large list: only names that contain the typed letters, share a word, or start the same way are compared
        key = compact(q)
        shared = [InventoryItem.token_key.contains(w) for w in tokens(q) if len(w) >= 3]
        stmt = stmt.where(or_(InventoryItem.compact_key.contains(key), InventoryItem.compact_key.startswith(key[:3]), *shared)).limit(500)
    return find_similar(q, db.execute(stmt).all())


@router.post("/items", status_code=201)
def create_item(body: ItemIn, user: User = Depends(require("inventory.manage")), db: Session = Depends(get_db)):
    _check_links(db, body.category_id, body.unit_id, body.supplier_id)
    _check_suppliers(db, body.supplier_ids)
    if body.opening_qty and body.opening_location_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Opening stock needs a location")
    name = " ".join(body.name.split())
    _check_duplicate(db, name)
    data = body.model_dump(exclude={"opening_location_id", "name", "supplier_ids"})
    item = InventoryItem(code=f"NEW-{uuid.uuid4().hex[:24]}", name=name, name_key=norm(name), **data)
    db.add(item)
    db.flush()
    _set_other_suppliers(db, item, body.supplier_ids)
    number = item.id
    while db.scalar(select(InventoryItem.id).where(InventoryItem.code == f"ITM-{number:05d}")):
        number += 1
    item.code = f"ITM-{number:05d}"  # every item gets its own generated ID
    if body.opening_qty:
        check_location(user, db, body.opening_location_id)
        post_txn(db, user, item, body.opening_location_id, "opening", body.opening_qty, "Opening stock")
    audit(db, user, "inventory.item_create", "inventory_item", item.id, None, body.model_dump(mode="json"))
    db.commit()
    return _serialize_items(db, user, [item], None)[0]


@router.put("/items/{item_id}")
def update_item(item_id: int, body: ItemUpdate, user: User = Depends(require("inventory.manage")),
                db: Session = Depends(get_db)):
    item = db.get(InventoryItem, item_id)
    if not item:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")
    data = body.model_dump(exclude_unset=True)
    others = data.pop("supplier_ids", None)
    _check_links(db, data.get("category_id"), data.get("unit_id"), data.get("supplier_id"))
    if others is not None:
        _check_suppliers(db, others)
    if "name" in data:
        data["name"] = " ".join(data["name"].split())
        _check_duplicate(db, data["name"], item.id)
    if data.get("unit_id", item.unit_id) != item.unit_id and db.scalar(select(StockTransaction.id).where(StockTransaction.item_id == item.id).limit(1)):
        raise HTTPException(status.HTTP_409_CONFLICT, "This item already has stock movements, so its unit cannot change. Add a new item with the other unit instead.")
    if data.get("active") is False and item.active:
        on_hand = db.scalar(select(func.coalesce(func.sum(InventoryBalance.qty), 0)).where(InventoryBalance.item_id == item.id))
        if on_hand != 0:
            raise HTTPException(status.HTTP_409_CONFLICT, f"{on_hand} of {item.name} are still on the books. Issue, transfer or write them off before making it inactive.")
    minimum = data.get("min_level", item.min_level)
    target = data.get("target_level", item.target_level)
    if target is not None and target < minimum:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The target level cannot be below the minimum level")
    before = {k: str(getattr(item, k)) for k in data}
    for key, value in data.items():
        setattr(item, key, value)
    if others is not None:
        _set_other_suppliers(db, item, others)
    if "name" in data:
        item.name_key = norm(data["name"])
    audit(db, user, "inventory.item_update", "inventory_item", item.id, before,
          {k: str(v) for k, v in data.items()})
    db.commit()
    return _serialize_items(db, user, [item], None)[0]


@router.post("/items/{item_id}/image")
async def set_item_image(item_id: int, file: UploadFile, user: User = Depends(require("inventory.manage")), db: Session = Depends(get_db)):
    """Keeps a small compressed copy of the picture as the item's thumbnail, replacing any earlier one."""
    item = db.get(InventoryItem, item_id)
    if not item:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")
    data = await file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "The picture must be under 5 MB")
    if file_kind(data[:16]) not in ("jpg", "png", "webp"):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "The picture must be a JPEG, PNG or WebP image")
    try:
        thumbnail = thumbnail_jpeg(data)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    name = f"{uuid.uuid4().hex}.jpg"
    upload_path(name).parent.mkdir(parents=True, exist_ok=True)
    upload_path(name).write_bytes(thumbnail)
    earlier, item.image_path = item.image_path, name
    audit(db, user, "inventory.item_image", "inventory_item", item.id, None, {"image_path": name})
    db.commit()
    if earlier:
        upload_path(earlier).unlink(missing_ok=True)
    return {"image_path": name}


@router.delete("/items/{item_id}/image")
def remove_item_image(item_id: int, user: User = Depends(require("inventory.manage")), db: Session = Depends(get_db)):
    item = db.get(InventoryItem, item_id)
    if not item:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")
    earlier, item.image_path = item.image_path, None
    audit(db, user, "inventory.item_image", "inventory_item", item.id, {"image_path": earlier}, {"image_path": None})
    db.commit()
    if earlier:
        upload_path(earlier).unlink(missing_ok=True)
    return {"image_path": None}


class LevelIn(BaseModel):
    min_level: int | None = Field(ge=0, le=MAX_LEVEL)


@router.put("/items/{item_id}/levels/{location_id}")
def set_location_minimum(item_id: int, location_id: int, body: LevelIn, user: User = Depends(require("inventory.count")),
                         db: Session = Depends(get_db)):
    """Sets the minimum for one item at one location; null goes back to the item's own minimum."""
    item = db.get(InventoryItem, item_id)
    if not item:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")
    check_location(user, db, location_id)
    if body.min_level is not None and item.target_level is not None and body.min_level > item.target_level:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The minimum cannot be above the item's target level")
    level = db.get(InventoryLevel, (item_id, location_id))
    before = level.min_level if level else None
    if body.min_level is None:
        if level:
            db.delete(level)
    elif level:
        level.min_level = body.min_level
    else:
        db.add(InventoryLevel(item_id=item_id, location_id=location_id, min_level=body.min_level))
        if db.get(InventoryBalance, (item_id, location_id)) is None:
            db.add(InventoryBalance(item_id=item_id, location_id=location_id, qty=0))  # an empty place can then show as short
    audit(db, user, "inventory.level_update", "inventory_item", item_id, {"location_id": location_id, "min_level": before},
          {"location_id": location_id, "min_level": body.min_level})
    db.commit()
    return {"item_id": item_id, "location_id": location_id, "override": body.min_level is not None,
            "minimum": body.min_level if body.min_level is not None else item.min_level}


@router.get("/shortages")
def shortages(location_id: int | None = None, user: User = Depends(require("inventory.module")), db: Session = Depends(get_db)):
    """Every item below its minimum at a location, with the other locations that hold more than they need."""
    scope = _scope(db, user, location_id)
    short = sorted(shortage_rows(db, scope), key=lambda r: (r[1].code, r[0].location_id))
    places = {loc.id: loc.name for loc in db.scalars(select(Location))}
    levels = level_map(db)
    ids = {item.id for _, item, _ in short}
    spare: dict[int, list[dict]] = {}
    if ids:
        held = select(InventoryBalance).where(InventoryBalance.item_id.in_(ids))
        visible = scoped_locations(user, db)
        if visible is not None:
            held = held.where(InventoryBalance.location_id.in_(visible))
        items = {item.id: item for _, item, _ in short}
        for bal in db.scalars(held):
            extra = bal.qty - levels.get((bal.item_id, bal.location_id), items[bal.item_id].min_level)
            if extra > 0:
                spare.setdefault(bal.item_id, []).append({"location_id": bal.location_id, "location": places[bal.location_id], "spare": extra})
    rows = []
    for bal, item, minimum in short:
        donors = sorted((d for d in spare.get(item.id, []) if d["location_id"] != bal.location_id), key=lambda d: -d["spare"])
        need = (item.target_level or minimum) - bal.qty
        rows.append({"item_id": item.id, "code": item.code, "name": item.name, "location_id": bal.location_id,
                     "location": places[bal.location_id], "qty": bal.qty, "minimum": minimum, "donors": donors,
                     "suggested_qty": min(need, donors[0]["spare"]) if donors else 0})
    return {"total": len(rows), "empty": sum(1 for r in rows if r["qty"] <= 0), "items": rows}


def get_item_or_404(db: Session, item_id: int) -> InventoryItem:
    item = db.get(InventoryItem, item_id)
    if not item:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")
    return item


@router.post("/transactions", status_code=201)
def post_transaction(body: TxnIn, user: User = Depends(require("stock.transfer")), db: Session = Depends(get_db)):
    check_location(user, db, body.location_id)
    item = get_item_or_404(db, body.item_id)
    if not item.active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{item.name} is retired; restore it before moving stock")
    if body.txn_type in ("adjustment", "opening"):
        if "stock.approve" not in permissions_of(user):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a manager can post stock adjustments or opening stock")
        if body.qty == 0 or (body.txn_type == "opening" and body.qty < 0):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Quantity must be positive" if body.txn_type == "opening" else "Adjustment must not be zero")
    elif body.qty <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Quantity must be positive")
    if body.txn_type in ("adjustment", "damage", "opening") and not (body.reason and len(body.reason.strip()) >= 5):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A reason is required")
    if body.txn_type == "opening" and db.scalar(select(StockTransaction.id).where(
            StockTransaction.item_id == item.id, StockTransaction.location_id == body.location_id, StockTransaction.txn_type == "opening").limit(1)):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Opening stock of {item.name} was already recorded here. Post an adjustment to correct the quantity.")
    try:
        txn = post_txn(db, user, item, body.location_id, body.txn_type, body.qty, body.reason)
    except StockError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    if body.txn_type in ("adjustment", "opening"):
        audit(db, user, f"inventory.{body.txn_type}", "stock_transaction", txn.id, None,
              {"item_id": item.id, "delta": txn.qty_delta, "reason": body.reason})
    db.commit()
    return row(txn, "id", "item_id", "location_id", "txn_type", "qty_delta", "occurred_at", "user_id", "reason")


@router.get("/transactions")
def list_transactions(item_id: int | None = None, location_id: int | None = None, txn_type: str | None = None,
                      date_from: date | None = None, date_to: date | None = None, page: int = 1, size: int = 25,
                      user: User = Depends(require("inventory.module")), db: Session = Depends(get_db)):
    stmt = select(StockTransaction)
    scope = _scope(db, user, location_id)
    if scope is not None:
        stmt = stmt.where(StockTransaction.location_id.in_(scope))
    if item_id is not None:
        stmt = stmt.where(StockTransaction.item_id == item_id)
    if txn_type:
        stmt = stmt.where(StockTransaction.txn_type == txn_type)
    if date_from:
        stmt = stmt.where(StockTransaction.occurred_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        stmt = stmt.where(StockTransaction.occurred_at < datetime.combine(date_to + timedelta(days=1), datetime.min.time()))
    total, rows = paginate(db, stmt.order_by(StockTransaction.id.desc()), page, size)
    names = dict(db.execute(select(Employee.user_id, Employee.full_name)).all())
    receipt_ids = {t.ref_id for t, in rows if t.ref_type in ("receipt", "receipt_void") and t.ref_id}
    invoice_dates = {rid: day.date().isoformat() for rid, day in db.execute(
        select(Receipt.id, Receipt.invoice_date).where(Receipt.id.in_(receipt_ids), Receipt.invoice_date.is_not(None)))} if receipt_ids else {}
    return {"total": total, "items": [
        {**row(t, "id", "item_id", "location_id", "txn_type", "qty_delta", "occurred_at", "reason", "ref_type", "ref_id"),
         "invoice_date": invoice_dates.get(t.ref_id) if t.ref_type in ("receipt", "receipt_void") else None,
         "user": names.get(t.user_id)} for t, in rows]}


@router.get("/assets")
def list_assets(item_id: int | None = None, location_id: int | None = None,
                user: User = Depends(require("inventory.view")), db: Session = Depends(get_db)):
    stmt = select(TrackedAsset)
    scope = _scope(db, user, location_id)
    if scope is not None:
        stmt = stmt.where(TrackedAsset.location_id.in_(scope))
    if item_id is not None:
        stmt = stmt.where(TrackedAsset.item_id == item_id)
    return [row(a, "id", "item_id", "asset_tag", "location_id", "condition", "custodian_employee_id")
            for a in db.scalars(stmt.order_by(TrackedAsset.asset_tag))]


@router.post("/assets", status_code=201)
def create_asset(body: AssetIn, user: User = Depends(require("inventory.manage")), db: Session = Depends(get_db)):
    item = get_item_or_404(db, body.item_id)
    if not item.is_tracked_asset:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Item is not configured as a tracked asset")
    check_location(user, db, body.location_id)
    asset = TrackedAsset(**body.model_dump())
    try:
        db.add(asset)
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Asset tag already exists") from None
    audit(db, user, "inventory.asset_create", "tracked_asset", asset.id, None, body.model_dump())
    db.commit()
    return row(asset, "id", "item_id", "asset_tag", "location_id", "condition", "custodian_employee_id")


@router.put("/assets/{asset_id}")
def update_asset(asset_id: int, body: AssetUpdate, user: User = Depends(require("inventory.count")),
                 db: Session = Depends(get_db)):
    asset = db.get(TrackedAsset, asset_id)
    if not asset:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Asset not found")
    check_location(user, db, asset.location_id)
    data = body.model_dump(exclude_unset=True)
    if "location_id" in data:
        check_location(user, db, data["location_id"])
    before = {k: getattr(asset, k) for k in data}
    for key, value in data.items():
        setattr(asset, key, value)
    audit(db, user, "inventory.asset_update", "tracked_asset", asset.id, before, data)
    db.commit()
    return row(asset, "id", "item_id", "asset_tag", "location_id", "condition", "custodian_employee_id")


@router.delete("/categories/{category_id}")
def delete_category(category_id: int, user: User = Depends(require("inventory.manage")), db: Session = Depends(get_db)):
    category = db.get(InventoryCategory, category_id)
    if not category:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Category not found")
    delete_if_unused(db, category, category.name)
    audit(db, user, "inventory.category_delete", "inventory_category", category_id, {"name": category.name}, None)
    db.commit()
    return {"deleted": category_id}


@router.delete("/units/{unit_id}")
def delete_unit(unit_id: int, user: User = Depends(require("inventory.manage")), db: Session = Depends(get_db)):
    unit = db.get(InventoryUnit, unit_id)
    if not unit:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unit not found")
    delete_if_unused(db, unit, unit.name)
    audit(db, user, "inventory.unit_delete", "inventory_unit", unit_id, {"name": unit.name}, None)
    db.commit()
    return {"deleted": unit_id}


@router.delete("/items/{item_id}")
def delete_item(item_id: int, user: User = Depends(require("inventory.manage")), db: Session = Depends(get_db)):
    item = db.get(InventoryItem, item_id)
    if not item:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")
    before = {"code": item.code, "name": item.name}
    picture = item.image_path
    delete_if_unused(db, item, item.name, cascade=frozenset({"inventory_level"}))
    audit(db, user, "inventory.item_delete", "inventory_item", item_id, before, None)
    db.commit()
    if picture:
        upload_path(picture).unlink(missing_ok=True)
    return {"deleted": item_id}
