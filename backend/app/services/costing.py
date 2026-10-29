"""Stock cost over a period at weighted average cost: opening value, purchases, closing value and what that means was consumed."""
from collections import defaultdict
from datetime import datetime, time
from decimal import Decimal

from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session

from .. import timeutil
from .inventory import ledger_kind
from ..models import BreakageIncident, InventoryBalance, InventoryCategory, InventoryItem, Location, Receipt, ReceiptLine, StockTransaction

RECEIPT_REFS = ("receipt", "receipt_void")

MEASURES = ("opening_value", "purchases", "returns", "transfers_in", "transfers_out", "closing_value", "cost_consumed", "issued",
            "breakage_damage", "missing_written_off", "baseline_adjustments", "count_adjustments")


def cost_report(db: Session, location_id: int, start: datetime, end: datetime) -> dict:
    """Per item and in total for [start, end): cost consumed = opening + purchases + returns + transfers in - transfers out - closing.

    A purchase counts on its invoice date when it has one and a breakage on the day it was reported (the ledger keeps the day it was entered or
    approved); everything else counts when it happened.
    """
    inside = case((StockTransaction.occurred_at >= start, 1), else_=0)
    worth = func.sum(StockTransaction.qty_delta * func.coalesce(StockTransaction.unit_cost, 0))
    invoice = and_(Receipt.id == StockTransaction.ref_id, StockTransaction.ref_type.in_(RECEIPT_REFS))
    kind = ledger_kind(split_writeoffs=True)
    sums = db.execute(
        select(StockTransaction.item_id, kind, inside, func.sum(StockTransaction.qty_delta), worth)
        .outerjoin(Receipt, invoice)
        .where(StockTransaction.location_id == location_id, StockTransaction.occurred_at < end, Receipt.invoice_date.is_(None),
               StockTransaction.ref_type.is_distinct_from("breakage"))
        .group_by(StockTransaction.item_id, kind, inside)).all()
    tz = db.get(Location, location_id).timezone
    sums = [*sums, *_by_invoice_date(db, location_id, tz, start, end, invoice), *_by_incident_date(db, location_id, start, end)]
    qty_before: dict[int, int] = defaultdict(int)
    value_before: dict[int, Decimal] = defaultdict(Decimal)
    flow: dict[int, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    qty_flow: dict[int, int] = defaultdict(int)
    kind_qty: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))  # units by kind of movement, for the quantity columns of the detailed report
    loaded: dict[int, int] = defaultdict(int)  # opening stock loaded inside the period counts as opening
    for item_id, txn_type, in_window, qty, value in sums:
        value = Decimal(str(value or 0))
        if in_window:
            flow[item_id][txn_type] += value
            kind_qty[item_id][txn_type] += qty
            qty_flow[item_id] += qty
            if txn_type == "opening":
                loaded[item_id] += qty
        else:
            qty_before[item_id] += qty
            value_before[item_id] += value
    ids = set(qty_before) | set(flow)
    found = list(db.scalars(select(InventoryItem).where(InventoryItem.id.in_(ids)))) if ids else []
    names = {i.id: (i.code, i.name) for i in found}
    categories = {c.id: c.name for c in db.scalars(select(InventoryCategory))}
    category_of = {i.id: categories.get(i.category_id, "Uncategorised") for i in found}
    averages = dict(db.execute(select(InventoryBalance.item_id, InventoryBalance.avg_cost).where(InventoryBalance.location_id == location_id)).all())
    rows, totals = [], defaultdict(Decimal)
    by_category: dict[str, dict] = defaultdict(lambda: defaultdict(Decimal))
    for item_id in sorted(ids, key=lambda i: names[i][0]):
        f = flow[item_id]
        opening = value_before[item_id] + f["opening"]
        closing = value_before[item_id] + sum(f.values())
        consumed = opening + f["receipt"] + f["return"] + f["transfer_in"] + f["transfer_out"] + f["baseline"] - closing
        row = {"item_id": item_id, "code": names[item_id][0], "name": names[item_id][1], "category": category_of[item_id],
               "opening_qty": qty_before[item_id] + loaded[item_id], "closing_qty": qty_before[item_id] + qty_flow[item_id],
               "average_cost": float(averages[item_id]) if averages.get(item_id) is not None else None,
               "opening_value": opening, "purchases": f["receipt"], "returns": f["return"], "transfers_in": f["transfer_in"],
               "transfers_out": -f["transfer_out"], "closing_value": closing, "cost_consumed": consumed,
               "issued": -f["issue"], "breakage_damage": -(f["breakage"] + f["damage"]), "missing_written_off": -f["writeoff"],
               "baseline_adjustments": f["baseline"], "count_adjustments": f["adjustment"]}
        q = kind_qty[item_id]
        row_qty = {"purchases_qty": q["receipt"], "returns_qty": q["return"], "transfers_in_qty": q["transfer_in"], "transfers_out_qty": -q["transfer_out"],
                   "issued_qty": -q["issue"], "breakage_damage_qty": -(q["breakage"] + q["damage"]), "missing_written_off_qty": -q["writeoff"],
                   "baseline_adjustments_qty": q["baseline"], "count_adjustments_qty": q["adjustment"]}
        for key in MEASURES:
            totals[key] += row[key]
            by_category[row["category"]][key] += row[key]
            row[key] = round(float(row[key]), 3)
        by_category[row["category"]]["items"] += 1
        row.update({k: int(v) for k, v in row_qty.items()})
        rows.append(row)
    return {"rows": rows, "totals": {k: round(float(v), 3) for k, v in totals.items()}, "by_category": category_rows(by_category, totals["cost_consumed"])}


def _by_invoice_date(db: Session, location_id: int, tz: str, start: datetime, end: datetime, invoice) -> list[tuple]:
    """Purchases that carry an invoice date, as (item, type, inside the period, quantity, value) rows placed by that date."""
    grouped: dict[tuple, list] = defaultdict(lambda: [0, Decimal(0)])
    for item_id, txn_type, qty, cost, day, ref in db.execute(
            select(StockTransaction.item_id, StockTransaction.txn_type, StockTransaction.qty_delta, StockTransaction.unit_cost, Receipt.invoice_date,
                   StockTransaction.ref_type)
            .join(Receipt, invoice)
            .where(StockTransaction.location_id == location_id, Receipt.invoice_date.is_not(None))):
        if ref == "receipt" and txn_type == "issue":
            txn_type = "return"  # goods sent back to a supplier
        elif ref == "receipt_void":
            txn_type = "receipt" if qty < 0 else "return"  # a voided invoice or return reverses its own entry
        when = timeutil.local_to_utc(day.date(), time(0, 0), tz)
        if when >= end:
            continue
        entry = grouped[(item_id, txn_type, 1 if when >= start else 0)]
        entry[0] += qty
        entry[1] += qty * Decimal(str(cost or 0))
    return [(item_id, txn_type, inside, qty, value) for (item_id, txn_type, inside), (qty, value) in grouped.items()]


def _by_incident_date(db: Session, location_id: int, start: datetime, end: datetime) -> list[tuple]:
    """Breakage, damage and write-offs placed on the day they were reported, not the day a manager approved them."""
    grouped: dict[tuple, list] = defaultdict(lambda: [0, Decimal(0)])
    for item_id, txn_type, qty, cost, when in db.execute(
            select(StockTransaction.item_id, StockTransaction.txn_type, StockTransaction.qty_delta, StockTransaction.unit_cost, BreakageIncident.occurred_at)
            .join(BreakageIncident, and_(BreakageIncident.id == StockTransaction.ref_id, StockTransaction.ref_type == "breakage"))
            .where(StockTransaction.location_id == location_id)):
        if when >= end:
            continue
        kind = "writeoff" if txn_type == "adjustment" else txn_type
        entry = grouped[(item_id, kind, 1 if when >= start else 0)]
        entry[0] += qty
        entry[1] += qty * Decimal(str(cost or 0))
    return [(item_id, kind, inside, qty, value) for (item_id, kind, inside), (qty, value) in grouped.items()]


def category_rows(by_category: dict[str, dict], consumed_total: Decimal) -> list[dict]:
    """One line per category with its share of the cost consumed, largest first."""
    out = []
    for name, sums in sorted(by_category.items(), key=lambda kv: -kv[1]["cost_consumed"]):
        out.append({"category": name, "items": int(sums["items"]), **{k: round(float(sums[k]), 3) for k in MEASURES},
                    "share": round(float(sums["cost_consumed"] / consumed_total * 100), 1) if consumed_total else 0.0})
    return out



def last_purchases(db: Session, item_ids: list[int]) -> dict[int, dict]:
    """Each item's most recent priced purchase: unit price after its line discount, the invoice date (or entry day) and the supplier."""
    if not item_ids:
        return {}
    when = func.coalesce(Receipt.invoice_date, Receipt.received_at)
    rows = db.execute(
        select(ReceiptLine.item_id, ReceiptLine.line_total, ReceiptLine.qty, when, Receipt.supplier_id, StockTransaction.unit_cost)
        .join(Receipt, Receipt.id == ReceiptLine.receipt_id)
        .outerjoin(StockTransaction, StockTransaction.id == ReceiptLine.transaction_id)
        .where(ReceiptLine.item_id.in_(item_ids), Receipt.status == "posted", Receipt.doc_type == "receipt",
               ReceiptLine.line_total > 0, ReceiptLine.qty > 0)
        .order_by(when, Receipt.id))
    # oldest first, so the last row seen for an item is its latest purchase; the price is what a unit really cost, as the ledger holds it
    # (after the line discount and its share of the invoice discount)
    return {item_id: {"price": float((Decimal(str(cost)) if cost is not None else Decimal(str(total)) / qty).quantize(Decimal("0.001"))),
                      "date": day.date().isoformat() if hasattr(day, "date") else str(day)[:10], "supplier_id": supplier_id}
            for item_id, total, qty, day, supplier_id, cost in rows}
