"""One item's whole story from the ledger: what came in, what was adjusted or used, and what is left, with a running balance."""
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (BreakageIncident, CountRound, Employee, InventoryCount, Location, Receipt, StockTransaction, Supplier)

KINDS = {
    "opening": "Opening stock",
    "received": "Received on invoices",
    "invoice_void": "Voided invoices and returns",
    "supplier_return": "Returned to suppliers",
    "manual_receipt": "Received (entered by hand)",
    "return": "Returned into stock",
    "transfer_in": "Transferred in",
    "transfer_out": "Transferred out",
    "issue": "Issued",
    "breakage": "Breakage",
    "damage": "Damage",
    "written_off": "Missing or written off",
    "count_adjustment": "Physical count adjustments",
    "round_usage": "Count round: unaccounted stock",
    "round_baseline": "Count round: baseline",
    "round_in": "Count round: stock moved in",
    "round_out": "Count round: stock moved out",
    "adjustment": "Other adjustments",
}
ORDER = list(KINDS)


def kind_of(txn_type: str, ref_type: str | None, qty: int) -> str:
    """Which line of the story a ledger row belongs to."""
    if txn_type == "opening":
        return "opening"
    if ref_type == "receipt":
        return "received" if txn_type == "receipt" else "supplier_return"
    if ref_type == "receipt_void":
        return "invoice_void"
    if ref_type == "breakage":
        return {"breakage": "breakage", "damage": "damage"}.get(txn_type, "written_off")
    if ref_type == "count":
        return "count_adjustment"
    if ref_type == "count_baseline":
        return "round_baseline"
    if ref_type == "count_round":
        return {"transfer_in": "round_in", "transfer_out": "round_out"}.get(txn_type, "round_usage")
    if txn_type in ("transfer_in", "transfer_out", "issue", "return"):
        return txn_type
    return "manual_receipt" if txn_type == "receipt" else "adjustment"


def item_history(db: Session, item_id: int, location_ids: set[int] | None, date_from: date | None, date_to: date | None, with_cost: bool) -> dict:
    stmt = select(StockTransaction).where(StockTransaction.item_id == item_id)
    if location_ids is not None:
        stmt = stmt.where(StockTransaction.location_id.in_(location_ids))
    rows = list(db.scalars(stmt.order_by(StockTransaction.occurred_at, StockTransaction.id)))
    start = datetime.combine(date_from, datetime.min.time()) if date_from else None
    end = datetime.combine(date_to + timedelta(days=1), datetime.min.time()) if date_to else None
    before = sum(t.qty_delta for t in rows if start and t.occurred_at < start)
    shown = [t for t in rows if (not start or t.occurred_at >= start) and (not end or t.occurred_at < end)]

    receipts = {r.id: r for r in db.scalars(select(Receipt).where(Receipt.id.in_({t.ref_id for t in shown if t.ref_type in ("receipt", "receipt_void") and t.ref_id} or {0})))}
    suppliers = {s.id: s.name for s in db.scalars(select(Supplier))}
    counts = {c.id for c in db.scalars(select(InventoryCount).where(InventoryCount.id.in_({t.ref_id for t in shown if t.ref_type == "count" and t.ref_id} or {0})))}
    rounds = {r.id: r.name for r in db.scalars(select(CountRound).where(CountRound.id.in_({t.ref_id for t in shown if t.ref_type in ("count_round", "count_baseline") and t.ref_id} or {0})))}
    incidents = {i.id: i.code for i in db.scalars(select(BreakageIncident).where(BreakageIncident.id.in_({t.ref_id for t in shown if t.ref_type == "breakage" and t.ref_id} or {0})))}
    places = {loc.id: loc.name for loc in db.scalars(select(Location))}
    people = dict(db.execute(select(Employee.user_id, Employee.full_name)).all())

    def document(t: StockTransaction) -> str | None:
        if t.ref_type in ("receipt", "receipt_void") and t.ref_id in receipts:
            r = receipts[t.ref_id]
            return f"Invoice {r.invoice_number} ({suppliers.get(r.supplier_id, 'supplier')})" + (" voided" if t.ref_type == "receipt_void" else "")
        if t.ref_type == "count":
            return f"Physical count #{t.ref_id}" if t.ref_id in counts else None
        if t.ref_type in ("count_round", "count_baseline"):
            return f"Count round: {rounds.get(t.ref_id, '#' + str(t.ref_id))}"
        if t.ref_type == "breakage":
            return f"Breakage report {incidents.get(t.ref_id, '#' + str(t.ref_id))}"
        if t.ref_type == "transfer":
            return f"Transfer #{t.ref_id}"
        return None

    totals: dict[str, int] = {}
    running, out = before, []
    for t in shown:
        kind = kind_of(t.txn_type, t.ref_type, t.qty_delta)
        totals[kind] = totals.get(kind, 0) + t.qty_delta
        running += t.qty_delta
        entry = {"id": t.id, "at": t.occurred_at.isoformat() + "Z", "location": places.get(t.location_id), "kind": kind, "label": KINDS[kind], "qty": t.qty_delta,
                 "balance": running, "document": document(t), "reason": t.reason, "by": people.get(t.user_id)}
        if with_cost:
            entry["unit_cost"] = float(t.unit_cost) if t.unit_cost is not None else None
        out.append(entry)
    closing = before + sum(totals.values())
    received_net = sum(totals.get(k, 0) for k in ("received", "invoice_void", "supplier_return"))
    return {"opening_balance": before, "closing": closing, "received_net": received_net,
            "totals": [{"kind": k, "label": KINDS[k], "qty": totals[k]} for k in ORDER if totals.get(k)],
            "rows": list(reversed(out))}
