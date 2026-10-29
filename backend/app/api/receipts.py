from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import timeutil
from ..audit import audit
from ..db import get_db
from ..deps import check_location, require, scoped_locations
from ..models import Employee, InventoryItem, ItemSupplier, Location, Receipt, ReceiptLine, StockTransaction, Supplier, User
from ..pagination import paginate, row
from ..services.inventory import StockError, post_txn
from ..services.settings import get_setting

router = APIRouter(prefix="/api/receipts", tags=["receiving"])

DocType = Literal["receipt", "supplier_return"]
LABEL = {"receipt": "Goods receipt", "supplier_return": "Return to supplier"}
FIELDS = ("id", "doc_type", "supplier_id", "location_id", "invoice_number", "received_at", "received_by", "note",
          "status", "voided_by", "voided_at", "void_reason")


DiscountType = Literal["amount", "percent"]
THREE_PLACES = Decimal("0.001")  # prices, discounts and totals are kept to a thousandth


class LineIn(BaseModel):
    item_id: int
    qty: int = Field(gt=0, le=100000)
    unit_cost: Decimal | None = Field(default=None, ge=0)
    discount_type: DiscountType | None = None
    discount: Decimal | None = Field(default=None, ge=0)


class ReceiptIn(BaseModel):
    doc_type: DocType = "receipt"
    supplier_id: int
    location_id: int
    invoice_number: str = Field(min_length=1, max_length=60)
    invoice_date: date | None = None
    received_on: date | None = None  # the day the goods arrived; today when left out
    note: str | None = Field(default=None, max_length=1000)
    discount_type: DiscountType | None = None
    discount: Decimal | None = Field(default=None, ge=0)
    lines: list[LineIn] = Field(min_length=1, max_length=200)


class EditIn(BaseModel):
    """What can change on a posted document without touching stock: its labels, dates and note."""

    invoice_number: str | None = Field(default=None, min_length=1, max_length=60)
    invoice_date: date | None = None
    received_on: date | None = None
    note: str | None = Field(default=None, max_length=1000)


class VoidIn(BaseModel):
    reason: str = Field(min_length=5, max_length=500)


def _num(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def _serialize(db: Session, receipt: Receipt, lines: bool = False) -> dict:
    out = row(receipt, *FIELDS)
    out["invoice_date"] = receipt.invoice_date.date().isoformat() if receipt.invoice_date else None
    out["received_on"] = receipt.received_on.isoformat() if receipt.received_on else receipt.received_at.date().isoformat()
    for column in ("subtotal", "line_discount_total", "discount_value", "discount_amount", "total"):
        out[column] = _num(getattr(receipt, column))
    out["total_discount"] = _num((receipt.line_discount_total or 0) + (receipt.discount_amount or 0)) if receipt.total is not None else None
    out["supplier"] = db.scalar(select(Supplier.name).where(Supplier.id == receipt.supplier_id))
    out["received_by_name"] = db.scalar(select(Employee.full_name).where(Employee.user_id == receipt.received_by))
    if lines:
        items = {i.id: i for i in db.scalars(select(InventoryItem))}
        out["lines"] = [{"item_id": ln.item_id, "code": items[ln.item_id].code, "name": items[ln.item_id].name,
                         "qty": ln.qty, "unit_cost": _num(ln.unit_cost),
                         "gross": _num(ln.qty * ln.unit_cost) if ln.unit_cost is not None else None,
                         "discount_type": ln.discount_type, "discount_value": _num(ln.discount_value),
                         "discount_amount": _num(ln.discount_amount), "line_total": _num(ln.line_total),
                         "transaction_id": ln.transaction_id}
                        for ln in db.scalars(select(ReceiptLine).where(ReceiptLine.receipt_id == receipt.id).order_by(ReceiptLine.id))]
    return out


def _per_unit(total: Decimal | None, qty: int) -> Decimal | None:
    """What one unit really cost after discounts, to four places so a small price difference is not rounded away."""
    return (total / qty).quantize(Decimal("0.0001")) if total is not None else None


def _money(value: Decimal) -> Decimal:
    return value.quantize(THREE_PLACES, rounding=ROUND_HALF_UP)


def _discount(kind: str | None, value: Decimal | None, base: Decimal, label: str) -> Decimal:
    """A discount in money from an amount or a percentage of `base`; it can never exceed `base`."""
    if not value:
        return Decimal("0.00")
    if kind == "percent":
        if value > 100:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{label}: a percentage discount cannot exceed 100")
        amount = _money(base * value / 100)
    else:
        amount = _money(value)
    if amount > base:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{label}: the discount ({amount}) is more than the amount it applies to ({base})")
    return amount


def _get(db: Session, user: User, receipt_id: int) -> Receipt:
    receipt = db.get(Receipt, receipt_id)
    if not receipt:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Receipt not found")
    check_location(user, db, receipt.location_id)
    return receipt


def check_month_open(db: Session, day: date | None) -> None:
    """Refuses to change a month a manager has locked (Settings > Receiving), so closed figures stay as they were reported."""
    locked = get_setting(db, "stock.lock_through")
    if day and locked and day.year * 100 + day.month <= locked:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{day:%B %Y} is locked: stock figures up to {locked // 100}-{locked % 100:02d} cannot change. "
                            "A manager can change the lock in Settings > Receiving")


def _document_day(receipt: Receipt) -> date:
    return receipt.invoice_date.date() if receipt.invoice_date else receipt.received_on or receipt.received_at.date()


def _check_dates(db: Session, today: date, invoice_date: date | None, received_on: date | None) -> None:
    if invoice_date and invoice_date > today:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The invoice date cannot be in the future")
    if invoice_date and invoice_date < today - timedelta(days=730) and not get_setting(db, "receiving.allow_old_invoices"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The invoice is more than two years old. A manager can allow old invoices in Settings > Receiving")
    if received_on and received_on > today:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The goods cannot have been received in the future")


def _post(db: Session, user: User, body: ReceiptIn) -> Receipt:
    """Validates and posts a document and its ledger rows; the caller commits, so a failure can undo more than this."""
    check_location(user, db, body.location_id)
    supplier = db.get(Supplier, body.supplier_id)
    if not supplier or not supplier.active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown or inactive supplier")
    ids = [ln.item_id for ln in body.lines]
    if len(set(ids)) != len(ids):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Each item can appear once; combine the quantities")
    items = {i.id: i for i in db.scalars(select(InventoryItem).where(InventoryItem.id.in_(ids)))}
    for item_id in ids:
        if item_id not in items or not items[item_id].active:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown or inactive item (id {item_id})")
    invoice = " ".join(body.invoice_number.split()).upper()
    if not invoice:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Enter the invoice number")
    today = timeutil.local_date(timeutil.utc_now(), db.get(Location, body.location_id).timezone)
    _check_dates(db, today, body.invoice_date, body.received_on)
    check_month_open(db, body.invoice_date or body.received_on or today)
    duplicate = db.scalar(select(Receipt).where(Receipt.supplier_id == supplier.id, Receipt.invoice_number == invoice,
                                                Receipt.status == "posted"))
    if duplicate:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Invoice {invoice} from {supplier.name} was already posted (document #{duplicate.id})")

    # Money: line total = quantity x unit cost less the line discount; subtotal = sum of the undiscounted line amounts;
    # total = subtotal less every line discount and the invoice discount.
    priced = []
    for ln in body.lines:
        if ln.unit_cost is None:
            if ln.discount:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{items[ln.item_id].name}: enter a unit cost before a discount")
            priced.append((None, Decimal("0.00"), None))
            continue
        gross = _money(ln.qty * ln.unit_cost)
        cut = _discount(ln.discount_type, ln.discount, gross, items[ln.item_id].name)
        priced.append((gross, cut, gross - cut))
    costed = any(gross is not None for gross, _, _ in priced)
    if not costed and body.discount:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Enter unit costs before an invoice discount")
    subtotal = sum((g for g, _, _ in priced if g is not None), Decimal("0.00")) if costed else None
    line_discounts = sum((d for _, d, _ in priced), Decimal("0.00")) if costed else None
    doc_discount = _discount(body.discount_type, body.discount, subtotal - line_discounts, "Invoice") if costed else None
    total = subtotal - line_discounts - doc_discount if costed else None

    receipt = Receipt(doc_type=body.doc_type, supplier_id=supplier.id, location_id=body.location_id, invoice_number=invoice,
                      invoice_date=datetime.combine(body.invoice_date, datetime.min.time()) if body.invoice_date else None,
                      received_at=timeutil.utc_now(), received_on=body.received_on or today, received_by=user.id, note=body.note, subtotal=subtotal,
                      line_discount_total=line_discounts, discount_type=body.discount_type if body.discount else None,
                      discount_value=body.discount or None, discount_amount=doc_discount, total=total)
    try:
        db.add(receipt)
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, f"Invoice {invoice} from {supplier.name} was already posted") from None

    # an invoice-level discount is spread over the lines in proportion to what they cost, so it lowers the cost of the stock
    keep = 1 - doc_discount / (subtotal - line_discounts) if costed and subtotal - line_discounts > 0 else Decimal(1)
    txn_type = "receipt" if body.doc_type == "receipt" else "issue"
    reason = f"{LABEL[body.doc_type]} #{receipt.id}, invoice {invoice} ({supplier.name})"
    cost_changes = {}
    try:
        for ln, (gross, cut, net) in zip(body.lines, priced):
            item = items[ln.item_id]
            net_unit = _money(_per_unit(net * keep, ln.qty)) if net is not None else None  # what one unit really cost: after its line discount and its share of the invoice discount
            if body.doc_type == "receipt" and item.supplier_id != supplier.id and not db.get(ItemSupplier, (item.id, supplier.id)):
                db.add(ItemSupplier(item_id=item.id, supplier_id=supplier.id))  # bought from them now, so they are one of its suppliers
            txn = post_txn(db, user, item, body.location_id, txn_type, ln.qty, reason, "receipt", receipt.id,
                           unit_cost=_per_unit(net * keep if net is not None else None, ln.qty) if body.doc_type == "receipt" else None)
            db.add(ReceiptLine(receipt_id=receipt.id, item_id=item.id, qty=ln.qty, unit_cost=ln.unit_cost,
                               discount_type=ln.discount_type if ln.discount else None, discount_value=ln.discount or None,
                               discount_amount=cut if gross is not None else None, line_total=net, transaction_id=txn.id))
            if body.doc_type == "receipt" and net_unit is not None and item.unit_cost is None:  # the starting price is filled once, then left to be set by hand
                cost_changes[item.code] = {"from": None, "to": f"{net_unit:.3f}"}
                item.unit_cost = net_unit
    except StockError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    audit(db, user, "receipt.post", "receipt", receipt.id, None,
          {"doc_type": body.doc_type, "supplier": supplier.name, "invoice": invoice, "lines": len(body.lines),
           "subtotal": str(subtotal), "discounts": str((line_discounts or 0) + (doc_discount or 0)), "total": str(total),
           "cost_updates": cost_changes})
    return receipt


@router.post("", status_code=201)
def post_receipt(body: ReceiptIn, user: User = Depends(require("stock.transfer")), db: Session = Depends(get_db)):
    receipt = _post(db, user, body)
    db.commit()
    return _serialize(db, receipt, lines=True)


@router.get("")
def list_receipts(supplier_id: int | None = None, location_id: int | None = None, receipt_status: str | None = None,
                  q: str | None = None, date_from: date | None = None, date_to: date | None = None,
                  date_by: Literal["invoice", "received"] = "invoice", page: int = 1, size: int = 25, user: User = Depends(require("stock.transfer")), db: Session = Depends(get_db)):
    stmt = select(Receipt)
    scope = scoped_locations(user, db)
    if location_id is not None:
        check_location(user, db, location_id)
        stmt = stmt.where(Receipt.location_id == location_id)
    elif scope is not None:
        stmt = stmt.where(Receipt.location_id.in_(scope))
    if supplier_id is not None:
        stmt = stmt.where(Receipt.supplier_id == supplier_id)
    if receipt_status:
        stmt = stmt.where(Receipt.status == receipt_status)
    if q:
        stmt = stmt.where(or_(Receipt.invoice_number.ilike(f"%{q.strip()}%"), Receipt.note.ilike(f"%{q.strip()}%")))
    if date_by == "received":  # the day the goods arrived
        if date_from:
            stmt = stmt.where(func.coalesce(Receipt.received_on, func.date(Receipt.received_at)) >= date_from)
        if date_to:
            stmt = stmt.where(func.coalesce(Receipt.received_on, func.date(Receipt.received_at)) <= date_to)
    else:  # the invoice date, or the day entered when none was given
        if date_from:
            stmt = stmt.where(func.coalesce(Receipt.invoice_date, Receipt.received_at) >= datetime.combine(date_from, datetime.min.time()))
        if date_to:
            stmt = stmt.where(func.coalesce(Receipt.invoice_date, Receipt.received_at) < datetime.combine(date_to + timedelta(days=1), datetime.min.time()))
    total, rows = paginate(db, stmt.order_by(Receipt.id.desc()), page, size)
    return {"total": total, "items": [_serialize(db, r[0]) for r in rows]}


@router.get("/{receipt_id}")
def get_receipt(receipt_id: int, user: User = Depends(require("stock.transfer")), db: Session = Depends(get_db)):
    return _serialize(db, _get(db, user, receipt_id), lines=True)


@router.put("/{receipt_id}")
def edit_receipt(receipt_id: int, body: EditIn, user: User = Depends(require("stock.approve")), db: Session = Depends(get_db)):
    """Corrects the invoice number, dates or note of a posted document; items, quantities and prices change only by voiding and re-entering."""
    receipt = _get(db, user, receipt_id)
    if receipt.status != "posted":
        raise HTTPException(status.HTTP_409_CONFLICT, "A void document cannot be edited")
    data = body.model_dump(exclude_unset=True)
    if "invoice_number" in data:
        data["invoice_number"] = " ".join(data["invoice_number"].split()).upper()
        if not data["invoice_number"]:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Enter the invoice number")
    if data.get("received_on") is None:
        data.pop("received_on", None)  # the day goods arrived is always set; leaving it out keeps it
    today = timeutil.local_date(timeutil.utc_now(), db.get(Location, receipt.location_id).timezone)
    _check_dates(db, today, data.get("invoice_date"), data.get("received_on"))
    if "invoice_date" in data or "received_on" in data:
        check_month_open(db, _document_day(receipt))  # moving a document out of a locked month is as much a change as moving one in
        if data.get("invoice_date") or data.get("received_on"):
            check_month_open(db, data.get("invoice_date") or data.get("received_on"))
    if "invoice_number" in data and data["invoice_number"] != receipt.invoice_number:
        if db.scalar(select(Receipt.id).where(Receipt.supplier_id == receipt.supplier_id, Receipt.invoice_number == data["invoice_number"],
                                              Receipt.status == "posted", Receipt.id != receipt.id)):
            raise HTTPException(status.HTTP_409_CONFLICT, f"Invoice {data['invoice_number']} from this supplier was already posted")
    before = {k: _plain(getattr(receipt, k)) for k in data}
    for key, value in data.items():
        setattr(receipt, key, datetime.combine(value, datetime.min.time()) if key == "invoice_date" and value else value)
    after = {k: _plain(getattr(receipt, k)) for k in data}
    if before != after:
        audit(db, user, "receipt.edit", "receipt", receipt.id, before, after)
    db.commit()
    return _serialize(db, receipt, lines=True)


def _plain(value):
    return value.date().isoformat() if isinstance(value, datetime) else value.isoformat() if isinstance(value, date) else value


@router.post("/{receipt_id}/void")
def void_receipt(receipt_id: int, body: VoidIn, user: User = Depends(require("stock.approve")),
                 db: Session = Depends(get_db)):
    """Reverses a posted document with new ledger entries; nothing already posted is edited."""
    receipt = _get(db, user, receipt_id)
    _void(db, user, receipt, body.reason)
    db.commit()
    return _serialize(db, receipt, lines=True)


def _void(db: Session, user: User, receipt: Receipt, why: str, action: str = "receipt.void") -> None:
    if receipt.status != "posted":
        raise HTTPException(status.HTTP_409_CONFLICT, "Document is already void")
    check_month_open(db, _document_day(receipt))
    sign = -1 if receipt.doc_type == "receipt" else 1
    reason = f"Void of {LABEL[receipt.doc_type].lower()} #{receipt.id}: {why}"
    for ln in db.scalars(select(ReceiptLine).where(ReceiptLine.receipt_id == receipt.id)):
        posted = db.get(StockTransaction, ln.transaction_id) if receipt.doc_type == "receipt" and ln.transaction_id else None
        paid = posted.unit_cost if posted else None
        post_txn(db, user, db.get(InventoryItem, ln.item_id), receipt.location_id, "adjustment", sign * ln.qty, reason,
                 "receipt_void", receipt.id, allow_negative=True, reverse_cost=paid)
    receipt.status, receipt.voided_by, receipt.voided_at, receipt.void_reason = "void", user.id, timeutil.utc_now(), why
    audit(db, user, action, "receipt", receipt.id, {"status": "posted"}, {"status": "void", "reason": why})


class CorrectIn(ReceiptIn):
    reason: str = Field(min_length=5, max_length=300)


@router.post("/{receipt_id}/correct", status_code=201)
def correct_receipt(receipt_id: int, body: CorrectIn, user: User = Depends(require("stock.approve")), db: Session = Depends(get_db)):
    """Fixes the items, quantities, prices or discounts of a posted document: the old one is reversed and a corrected one posted in its place,
    all or nothing, so the ledger keeps both and stock ends up as if the right document had been entered at first."""
    old = _get(db, user, receipt_id)
    if body.doc_type != old.doc_type:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A correction cannot change the kind of document")
    _void(db, user, old, f"corrected: {body.reason}", "receipt.correct_void")
    new = _post(db, user, ReceiptIn(**body.model_dump(exclude={"reason"})))
    old.void_reason = f"Corrected by document #{new.id}: {body.reason}"
    audit(db, user, "receipt.correct", "receipt", new.id, {"replaces": old.id}, {"reason": body.reason, "new_document": new.id})
    db.commit()
    return _serialize(db, new, lines=True)
