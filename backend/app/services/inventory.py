from collections import defaultdict
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import and_, case, event, func, or_, select
from sqlalchemy.orm import Session

from .. import timeutil
from ..models import (InventoryBalance, InventoryCount, InventoryCountLine, InventoryItem, InventoryLevel, Location, StockSnapshot,
                      StockTransaction, User)
from ..permissions import MANAGER, SUPERVISOR
from .notify import notify, recipients
from .similarity import compact, token_key

# Direction of each transaction type; adjustments carry their own sign.
SIGN = {"opening": 1, "receipt": 1, "return": 1, "transfer_in": 1, "issue": -1, "damage": -1, "breakage": -1,
        "transfer_out": -1}
OUTFLOW_TYPES = ("issue", "damage", "breakage")


class StockError(Exception):
    pass


def level_map(db: Session) -> dict[tuple[int, int], int]:
    """Location minimums that override the item's own, keyed by (item id, location id)."""
    return {(i, loc): m for i, loc, m in db.execute(select(InventoryLevel.item_id, InventoryLevel.location_id, InventoryLevel.min_level))}


def below_minimum(locations: set[int] | None = None):
    """Rows of (balance, item, minimum) for every active item held below its minimum at a location."""
    minimum = func.coalesce(InventoryLevel.min_level, InventoryItem.min_level)
    stmt = (select(InventoryBalance, InventoryItem, minimum.label("minimum"))
            .join(InventoryItem, InventoryItem.id == InventoryBalance.item_id)
            .outerjoin(InventoryLevel, and_(InventoryLevel.item_id == InventoryBalance.item_id,
                                            InventoryLevel.location_id == InventoryBalance.location_id))
            .where(InventoryItem.active.is_(True), InventoryBalance.qty < minimum))
    return stmt if locations is None else stmt.where(InventoryBalance.location_id.in_(locations))


def unheld_items(db: Session) -> list[InventoryItem]:
    """Active items with a minimum that no location has ever held: they have no balance row, so nothing else reports them."""
    held = select(InventoryBalance.item_id).where(InventoryBalance.item_id == InventoryItem.id).exists()
    return list(db.scalars(select(InventoryItem).where(InventoryItem.active.is_(True), InventoryItem.min_level > 0, ~held)
                           .order_by(InventoryItem.code)))


def places_in(db: Session, locations: set[int] | None) -> list[int]:
    """Ids of the active locations, limited to `locations` when given."""
    return [i for i in db.scalars(select(Location.id).where(Location.active.is_(True)).order_by(Location.id)) if locations is None or i in locations]


def shortage_rows(db: Session, locations: set[int] | None = None) -> list[tuple[InventoryBalance, InventoryItem, int]]:
    """Every item below its minimum at a location, and each item never stocked anywhere as an empty row at every location."""
    rows = [(b, i, m) for b, i, m in db.execute(below_minimum(locations))]
    places = places_in(db, locations)
    return rows + [(InventoryBalance(item_id=i.id, location_id=p, qty=0), i, i.min_level) for i in unheld_items(db) for p in places]


@event.listens_for(InventoryItem, "before_insert")
@event.listens_for(InventoryItem, "before_update")
def _set_search_keys(_mapper, _connection, item: InventoryItem) -> None:
    """The two stored keys always follow the name, whichever code path creates or renames an item."""
    item.compact_key, item.token_key = compact(item.name), token_key(item.name)


def norm(text: str) -> str:
    """Case- and spacing-insensitive key used to stop near-duplicate names."""
    return " ".join(text.lower().split())


FOUR = Decimal("0.0001")


def _costed(item: InventoryItem, balance: InventoryBalance, delta: int, unit_cost: Decimal | None,
            reverse_cost: Decimal | None) -> Decimal | None:
    """The cost a movement is valued at, and the new weighted average held on the balance.

    Stock coming in at a price blends into the average; stock going out, and stock coming in without a price, leave it as it is.
    A reversal of a priced receipt takes that price back out of the average.
    """
    before = max(balance.qty, 0)
    base = balance.avg_cost if balance.avg_cost is not None else item.unit_cost
    if delta > 0:
        cost = unit_cost if unit_cost is not None else base
        if cost is not None:
            balance.avg_cost = cost if before == 0 or base is None else ((before * base + delta * cost) / (before + delta)).quantize(FOUR)
        return cost
    if reverse_cost is not None and base is not None and before + delta > 0:
        balance.avg_cost = ((before * base - (-delta) * reverse_cost) / (before + delta)).quantize(FOUR)
        return reverse_cost
    return base


def post_txn(db: Session, user: User, item: InventoryItem, location_id: int, txn_type: str, qty: int,
             reason: str | None = None, ref_type: str | None = None, ref_id: int | None = None,
             allow_negative: bool = False, unit_cost: Decimal | None = None,
             reverse_cost: Decimal | None = None, occurred_at: datetime | None = None) -> StockTransaction:
    """Appends one immutable ledger row, valued at the weighted average cost, and moves the balance in the caller's transaction."""
    delta = qty if txn_type == "adjustment" else SIGN[txn_type] * abs(qty)
    if delta == 0:
        raise StockError("Quantity must not be zero")
    balance = db.get(InventoryBalance, (item.id, location_id), with_for_update=True)
    if balance is None:
        balance = InventoryBalance(item_id=item.id, location_id=location_id, qty=0)
        db.add(balance)
        db.flush()
    if balance.qty + delta < 0 and not allow_negative:
        raise StockError(f"Insufficient stock of {item.name}: {balance.qty} available")
    cost = _costed(item, balance, delta, unit_cost, reverse_cost)
    balance.qty += delta
    txn = StockTransaction(item_id=item.id, location_id=location_id, txn_type=txn_type, qty_delta=delta,
                           occurred_at=occurred_at or timeutil.utc_now(), user_id=user.id, reason=reason, ref_type=ref_type,
                           ref_id=ref_id, unit_cost=cost)
    db.add(txn)
    db.flush()
    level = db.get(InventoryLevel, (item.id, location_id))
    minimum = level.min_level if level else item.min_level
    if delta < 0 and balance.qty < 0:
        place = db.get(Location, location_id).name
        notify(db, recipients(db, location_id, SUPERVISOR, MANAGER), "negative_stock",
               f"Stock below zero: {item.name} is {balance.qty} at {place}",
               key=f"negative:{item.id}:{location_id}:{timeutil.utc_now().date().isoformat()}", priority="high",
               location_id=location_id, link="/inventory", requires_ack=True,
               body="More was written off than the books show. Check the count and the receipts.")
    if delta < 0 and balance.qty < minimum:
        notify(db, recipients(db, location_id, SUPERVISOR, MANAGER), "low_stock",
               f"Low stock: {item.name} ({balance.qty} left, minimum {minimum})",
               key=f"low:{item.id}:{location_id}:{timeutil.utc_now().date().isoformat()}", priority="high",
               location_id=location_id, link="/inventory")
    return txn


def _month_bounds(tz: str, month: str) -> tuple[datetime, datetime]:
    year, mon = (int(p) for p in month.split("-"))
    first = date(year, mon, 1)
    following = date(year + (mon == 12), mon % 12 + 1, 1)
    return timeutil.local_to_utc(first, time(0), tz), timeutil.local_to_utc(following, time(0), tz)


def counts_as_received():
    """Invoices (with their voids and credit notes), opening stock and approved transfers in; manual increases and returns do not count."""
    return or_(StockTransaction.txn_type.in_(("opening", "transfer_in")), StockTransaction.ref_type.in_(("receipt", "receipt_void")))


def received_breakdown(db: Session, location_id: int, item_ids: list[int]) -> dict[int, dict[str, int]]:
    """What came into a location for each item, split into invoices, opening stock and transfers in."""
    if not item_ids:
        return {}
    rows = db.execute(select(StockTransaction.item_id, StockTransaction.txn_type, StockTransaction.ref_type, func.sum(StockTransaction.qty_delta)).where(
        StockTransaction.location_id == location_id, counts_as_received(), StockTransaction.item_id.in_(item_ids))
        .group_by(StockTransaction.item_id, StockTransaction.txn_type, StockTransaction.ref_type)).all()
    out: dict[int, dict[str, int]] = defaultdict(lambda: {"invoices": 0, "opening": 0, "transfers_in": 0})
    for item_id, txn_type, ref_type, total in rows:
        key = "invoices" if ref_type in ("receipt", "receipt_void") else "opening" if txn_type == "opening" else "transfers_in"
        out[item_id][key] += int(total)
    return out


def received_to_date(db: Session, location_id: int, item_ids: list[int]) -> dict[int, int]:
    """The most a count of each item can honestly be: invoices, opening stock and transfers in, less credit notes and voids."""
    return {item_id: max(sum(parts.values()), 0) for item_id, parts in received_breakdown(db, location_id, item_ids).items()}


def ledger_kind(split_writeoffs: bool = False):  # a first count round's accepted gap is its own line: not used stock, and not part of the opening
    """What a ledger row means for the reports: goods sent back to a supplier are returns, and a voided invoice or return reverses its own kind,
    rather than being read as stock used up or a count adjustment. With `split_writeoffs`, stock reported missing or written off is its own kind."""
    return case(
        *([(and_(StockTransaction.ref_type == "breakage", StockTransaction.txn_type == "adjustment"), "writeoff")] if split_writeoffs else []),
        (StockTransaction.ref_type == "count_baseline", "baseline"),
        (and_(StockTransaction.ref_type == "receipt", StockTransaction.txn_type == "issue"), "return"),
        (and_(StockTransaction.ref_type == "receipt_void", StockTransaction.qty_delta < 0), "receipt"),
        (StockTransaction.ref_type == "receipt_void", "return"),
        else_=StockTransaction.txn_type)


def reconcile(db: Session, location: Location, month: str) -> list[dict]:
    """Per item: opening + movements = closing, plus the latest posted physical count in the month.

    The ledger is summed by the database, grouped by item, movement type and before or inside the month, so the
    work is one pass over the rows instead of a scan of every movement for every item.
    """
    start, end = _month_bounds(location.timezone, month)
    items = db.scalars(select(InventoryItem).order_by(InventoryItem.code)).all()
    in_month = case((StockTransaction.occurred_at >= start, 1), else_=0)
    # Start from the latest stored month-end balance when there is one, so only the movements since then are summed.
    base_month = db.scalar(select(func.max(StockSnapshot.month)).where(
        StockSnapshot.location_id == location.id, StockSnapshot.month < month, StockSnapshot.value.is_not(None)))
    before: dict[int, int] = defaultdict(int)
    before_value: dict[int, Decimal] = defaultdict(Decimal)
    window = [StockTransaction.location_id == location.id, StockTransaction.occurred_at < end]
    if base_month:
        for item_id, qty, value in db.execute(select(StockSnapshot.item_id, StockSnapshot.qty, StockSnapshot.value).where(
                StockSnapshot.location_id == location.id, StockSnapshot.month == base_month)):
            before[item_id], before_value[item_id] = qty, value
        window.append(StockTransaction.occurred_at >= _month_bounds(location.timezone, base_month)[1])
    seen_before_start = set(before)
    worth = func.sum(StockTransaction.qty_delta * func.coalesce(StockTransaction.unit_cost, 0))
    kind = ledger_kind()
    sums = db.execute(
        select(StockTransaction.item_id, kind, in_month.label("in_month"), func.sum(StockTransaction.qty_delta), worth)
        .where(*window).group_by(StockTransaction.item_id, kind, in_month)).all()
    during: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    during_value: dict[int, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    for item_id, txn_type, inside, total, total_value in sums:
        if inside:
            during[item_id][txn_type] += total
            during_value[item_id][txn_type] += Decimal(str(total_value or 0))
        else:
            before[item_id] += total
            before_value[item_id] += Decimal(str(total_value or 0))
    moved = seen_before_start | set(before) | set(during)
    counts = db.execute(
        select(InventoryCountLine, InventoryCount).join(InventoryCount, InventoryCount.id == InventoryCountLine.count_id)
        .where(InventoryCount.location_id == location.id, InventoryCount.status == "posted",
               InventoryCount.counted_at >= start, InventoryCount.counted_at < end)
        .order_by(InventoryCount.counted_at)).all()
    last_count = {line.item_id: line for line, _ in counts}
    # a count's value is what its adjustment was posted at, so a later price change cannot move it
    adjusted = dict(db.execute(select(StockTransaction.id, StockTransaction.unit_cost).where(
        StockTransaction.id.in_([ln.adjustment_txn_id for ln in last_count.values() if ln.adjustment_txn_id]))).all()) if last_count else {}
    rows = []
    for item in items:
        if item.id not in moved and item.id not in last_count:
            continue
        mine = during[item.id]
        movements = {
            "opening_stock": mine["opening"], "receipts": mine["receipt"], "returns": mine["return"],
            "issues": mine["issue"], "breakage_damage": mine["breakage"] + mine["damage"],
            "transfers_in": mine["transfer_in"], "transfers_out": mine["transfer_out"],
            "adjustments": mine["adjustment"] + mine["baseline"],
        }
        closing = before[item.id] + sum(movements.values())
        worth_mine = during_value[item.id]
        values = {
            "receipts_value": worth_mine["receipt"], "returns_value": worth_mine["return"], "issues_value": worth_mine["issue"],
            "breakage_damage_value": worth_mine["breakage"] + worth_mine["damage"], "transfers_in_value": worth_mine["transfer_in"],
            "transfers_out_value": worth_mine["transfer_out"], "adjustments_value": worth_mine["adjustment"] + worth_mine["baseline"],
            "opening_stock_value": worth_mine["opening"]}
        closing_value = before_value[item.id] + sum(worth_mine.values())
        line = last_count.get(item.id)
        variance = line.counted_qty - line.system_qty if line else None
        posted_at = adjusted.get(line.adjustment_txn_id) if line else None
        cost = float(posted_at) if posted_at is not None else None
        rows.append({
            "item_id": item.id, "code": item.code, "name": item.name, "opening": before[item.id], **movements,
            "closing": closing, "counted_qty": line.counted_qty if line else None,
            "count_variance": variance, "variance_value": round(variance * cost, 3) if variance and cost is not None else None,
            "opening_value": round(float(before_value[item.id]), 3), "closing_value": round(float(closing_value), 3),
            **{k: round(float(v), 3) for k, v in values.items()},
            "value": round(float(closing_value), 3) if closing_value or closing else None,
        })
    return rows


def variance_summary(rows: list[dict]) -> dict:
    """Shortages and surpluses found by the month's posted counts, in units and in money."""
    short = [r for r in rows if r["count_variance"] and r["count_variance"] < 0]
    over = [r for r in rows if r["count_variance"] and r["count_variance"] > 0]
    return {"counted_items": sum(1 for r in rows if r["counted_qty"] is not None), "shortage_items": len(short),
            "surplus_items": len(over), "shortage_units": -sum(r["count_variance"] for r in short),
            "surplus_units": sum(r["count_variance"] for r in over),
            "net_value": round(sum(r["variance_value"] or 0 for r in rows), 3)}


def balance_matches_ledger(db: Session, item_id: int, location_id: int) -> bool:
    ledger = db.scalar(select(func.coalesce(func.sum(StockTransaction.qty_delta), 0)).where(
        StockTransaction.item_id == item_id, StockTransaction.location_id == location_id))
    balance = db.get(InventoryBalance, (item_id, location_id))
    return ledger == (balance.qty if balance else 0)
