import re
from typing import Literal
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import timeutil
from ..audit import audit
from ..db import get_db
from ..deps import check_location, permissions_of, require, scoped_locations
from ..models import (ApprovalRecord, CountDraft, InventoryBalance, InventoryCount, InventoryCountLine, InventoryItem,
                      InventoryTransfer, InventoryTransferLine, Location, StockTransaction, TrackedAsset, User)
from ..pagination import row
from ..permissions import MANAGER, SUPERVISOR
from ..services import metrics
from ..services.costing import MEASURES, category_rows, cost_report
from ..services.inventory import StockError, post_txn, received_breakdown, received_to_date, reconcile, variance_summary
from ..services.notify import holders_of, notify, recipients
from .inventory import get_item_or_404
from .receipts import check_month_open

router = APIRouter(prefix="/api/stock", tags=["stock"])

MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
TRANSFER_FIELDS = ("id", "from_location_id", "to_location_id", "status", "requested_by", "requested_at", "decided_by",
                   "decided_at", "note")


class LineIn(BaseModel):
    item_id: int
    qty: int = Field(gt=0)
    asset_ids: list[int] = Field(default_factory=list, max_length=1000)  # the tags that move, for a tracked item


class TransferIn(BaseModel):
    from_location_id: int
    to_location_id: int
    lines: list[LineIn] = Field(min_length=1)
    note: str | None = Field(default=None, max_length=500)
    moved_on: date | None = None  # a catch-up: the stock was already moved by hand on this day


class DecisionIn(BaseModel):
    approve: bool
    note: str | None = Field(default=None, max_length=500)


class CountLineIn(BaseModel):
    item_id: int
    counted_qty: int = Field(ge=0)
    reason: str | None = Field(default=None, max_length=500)  # required when the count is higher than the system quantity


class CountIn(BaseModel):
    location_id: int
    lines: list[CountLineIn] = Field(min_length=1)


def _transfer_dict(db: Session, transfer: InventoryTransfer) -> dict:
    """The transfer with each line valued: at what it went out at once completed, at today's average at the sender before."""
    lines = list(db.scalars(select(InventoryTransferLine).where(InventoryTransferLine.transfer_id == transfer.id)))
    sent = {t.item_id: t.unit_cost for t in db.scalars(select(StockTransaction).where(
        StockTransaction.ref_type == "transfer", StockTransaction.ref_id == transfer.id, StockTransaction.txn_type == "transfer_out"))}
    averages = {b.item_id: b.avg_cost for b in db.scalars(select(InventoryBalance).where(InventoryBalance.location_id == transfer.from_location_id))}
    out = []
    for ln in lines:
        cost = sent.get(ln.item_id) if transfer.status == "completed" else averages.get(ln.item_id)
        tags = list(db.scalars(select(TrackedAsset.asset_tag).where(TrackedAsset.id.in_(ln.asset_ids or [])).order_by(TrackedAsset.asset_tag)))
        out.append({**row(ln, "item_id", "qty"), "asset_tags": tags, "unit_cost": float(cost) if cost is not None else None,
                    "value": round(float(cost) * ln.qty, 3) if cost is not None else None})
    return {**row(transfer, *TRANSFER_FIELDS), "lines": out, "total_value": round(sum(l["value"] or 0 for l in out), 3)}


def _execute_transfer(db: Session, user: User, transfer: InventoryTransfer, occurred_at: datetime | None = None) -> None:
    for line in db.scalars(select(InventoryTransferLine).where(InventoryTransferLine.transfer_id == transfer.id)):
        item = db.get(InventoryItem, line.item_id)
        sent = post_txn(db, user, item, transfer.from_location_id, "transfer_out", line.qty, transfer.note,
                        "transfer", transfer.id, occurred_at=occurred_at)
        post_txn(db, user, item, transfer.to_location_id, "transfer_in", line.qty, transfer.note,
                 "transfer", transfer.id, unit_cost=sent.unit_cost, occurred_at=occurred_at)
        for asset in db.scalars(select(TrackedAsset).where(TrackedAsset.id.in_(line.asset_ids or []))):
            if asset.location_id != transfer.from_location_id:
                raise StockError(f"Asset {asset.asset_tag} is no longer at the sending location")
            asset.location_id = transfer.to_location_id
    transfer.status = "completed"
    transfer.decided_by, transfer.decided_at = user.id, timeutil.utc_now()


@router.get("/locations")
def destinations(user: User = Depends(require("stock.transfer")), db: Session = Depends(get_db)):
    """Every active location, so a transfer can target one the caller is not assigned to."""
    return [row(loc, "id", "code", "name") for loc in db.scalars(
        select(Location).where(Location.active.is_(True)).order_by(Location.name))]


@router.get("/location-stock")
def location_stock(location_id: int, user: User = Depends(require("stock.transfer")), db: Session = Depends(get_db)):
    """Every active item with what the location holds and its cost: the average there, else the item's own cost."""
    check_location(user, db, location_id)
    held = {b.item_id: b for b in db.scalars(select(InventoryBalance).where(InventoryBalance.location_id == location_id))}
    out = []
    for item in db.scalars(select(InventoryItem).where(InventoryItem.active.is_(True))):
        balance = held.get(item.id)
        cost = balance.avg_cost if balance is not None and balance.avg_cost is not None else item.unit_cost
        out.append({"item_id": item.id, "qty": balance.qty if balance else 0, "avg_cost": float(cost) if cost is not None else None})
    return out


def _check_assets(db: Session, body: TransferIn, wanted: dict[int, int]) -> None:
    """A tracked item moves with the tags named, as many as the quantity; any other item moves with none."""
    tags: dict[int, list[int]] = defaultdict(list)
    for ln in body.lines:
        tags[ln.item_id] += ln.asset_ids
    for item_id, qty in wanted.items():
        item, named = db.get(InventoryItem, item_id), tags[item_id]
        if not item.is_tracked_asset:
            if named:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{item.name} is not tracked by asset tag")
            continue
        if len(named) != qty or len(set(named)) != qty:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{item.name}: choose the {qty} asset tags that are moving")
        found = db.scalar(select(func.count(TrackedAsset.id)).where(
            TrackedAsset.id.in_(named), TrackedAsset.item_id == item_id, TrackedAsset.location_id == body.from_location_id))
        if found != qty:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{item.name}: every tag must be one of its assets at the sending location")


CATCH_UP_DAYS = 90


def _catch_up_time(db: Session, user: User, body: TransferIn) -> datetime:
    """When a transfer that already happened is placed in the ledger: midday of that day at the sender (or now, for today)."""
    if "stock.approve" not in permissions_of(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only someone who can approve transfers can record one that already happened")
    source = db.get(Location, body.from_location_id)
    now = timeutil.utc_now()
    today = timeutil.local_date(now, source.timezone)
    if body.moved_on > today or body.moved_on < today - timedelta(days=CATCH_UP_DAYS):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"The move must be dated today or within the last {CATCH_UP_DAYS} days")
    check_month_open(db, body.moved_on)
    moved = min(timeutil.local_to_utc(body.moved_on, time(12, 0), source.timezone), now)
    counted = db.scalar(select(func.max(InventoryCount.counted_at)).where(
        InventoryCount.status == "posted", InventoryCount.location_id.in_([body.from_location_id, body.to_location_id])))
    if counted and moved < counted:
        raise HTTPException(status.HTTP_409_CONFLICT, f"A count was posted on {counted.date().isoformat()}, after that day. "
                            "Date the move on or after the count, or leave the stock as the count left it")
    return moved


@router.post("/transfers", status_code=201)
def request_transfer(body: TransferIn, user: User = Depends(require("stock.transfer")), db: Session = Depends(get_db)):
    check_location(user, db, body.from_location_id)
    if not db.get(Location, body.to_location_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Destination location not found")
    if body.from_location_id == body.to_location_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Source and destination must differ")
    wanted: dict[int, int] = {}
    for line in body.lines:
        item = get_item_or_404(db, line.item_id)
        if not item.active:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{item.name} is retired")
        wanted[item.id] = wanted.get(item.id, 0) + line.qty
        on_hand = db.scalar(select(InventoryBalance.qty).where(InventoryBalance.item_id == item.id, InventoryBalance.location_id == body.from_location_id)) or 0
        if wanted[item.id] > on_hand:
            source = db.get(Location, body.from_location_id)
            message = f"Only {on_hand} of {item.name} are in stock at {source.name}; {wanted[item.id]} were asked for. Something is wrong: check the quantity and the stock."
            notify(db, recipients(db, source.id, SUPERVISOR, MANAGER), "transfer_over_stock",
                   f"Transfer asks for more than is in stock at {source.name}: {item.name} {wanted[item.id]} asked, {on_hand} held",
                   key=f"transferover:{source.id}:{item.id}:{user.id}:{timeutil.utc_now().isoformat(timespec='minutes')}", priority="high",
                   location_id=source.id, link="/stock-movements", requires_ack=True, body=message)
            audit(db, user, "stock.transfer_blocked", "inventory_item", item.id, None, {"from": source.id, "asked": wanted[item.id], "held": on_hand})
            db.commit()
            raise HTTPException(status.HTTP_409_CONFLICT, message)
    _check_assets(db, body, wanted)
    moved_at, note = None, body.note
    if body.moved_on:
        moved_at, note = _catch_up_time(db, user, body), f"Catch-up, moved on {body.moved_on.isoformat()}" + (f". {body.note}" if body.note else "")
    transfer = InventoryTransfer(from_location_id=body.from_location_id, to_location_id=body.to_location_id,
                                 requested_by=user.id, requested_at=moved_at or timeutil.utc_now(), note=note)
    db.add(transfer)
    db.flush()
    db.add_all(InventoryTransferLine(transfer_id=transfer.id, item_id=ln.item_id, qty=ln.qty, asset_ids=ln.asset_ids or None) for ln in body.lines)
    db.flush()
    if "stock.approve" in permissions_of(user):
        try:
            _execute_transfer(db, user, transfer, moved_at)
        except StockError as exc:
            db.rollback()
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
        db.add(ApprovalRecord(subject_type="transfer", subject_id=transfer.id, decision="approved", decided_by=user.id,
                              reason="Requested by approver"))
    else:
        notify(db, holders_of(db, "stock.approve", body.from_location_id), "transfer_pending", "Stock transfer awaiting approval",
               key=f"transfer:{transfer.id}", priority="high", location_id=body.from_location_id,
               link="/stock-movements")
    audit(db, user, "stock.transfer_request", "inventory_transfer", transfer.id, None, body.model_dump(mode="json"))
    db.commit()
    return _transfer_dict(db, transfer)


@router.get("/transfers")
def list_transfers(transfer_status: str | None = None, user: User = Depends(require("inventory.module")),
                   db: Session = Depends(get_db)):
    stmt = select(InventoryTransfer)
    scope = scoped_locations(user, db)
    if scope is not None:
        stmt = stmt.where(or_(InventoryTransfer.from_location_id.in_(scope), InventoryTransfer.to_location_id.in_(scope)))
    if transfer_status:
        stmt = stmt.where(InventoryTransfer.status == transfer_status)
    return [_transfer_dict(db, t) for t in db.scalars(stmt.order_by(InventoryTransfer.id.desc()).limit(100))]


@router.post("/transfers/{transfer_id}/decision")
def decide_transfer(transfer_id: int, body: DecisionIn, user: User = Depends(require("stock.approve")),
                    db: Session = Depends(get_db)):
    transfer = db.get(InventoryTransfer, transfer_id)
    if not transfer:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Transfer not found")
    if transfer.status != "requested":
        raise HTTPException(status.HTTP_409_CONFLICT, f"Transfer is already {transfer.status}")
    if transfer.requested_by == user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You cannot approve your own request")
    if body.approve:
        try:
            _execute_transfer(db, user, transfer)
        except StockError as exc:
            db.rollback()
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    else:
        transfer.status, transfer.decided_by, transfer.decided_at = "rejected", user.id, timeutil.utc_now()
        notify(db, [transfer.requested_by], "transfer_rejected", "Stock transfer rejected",
               key=f"transfer_rejected:{transfer.id}", body=body.note, location_id=transfer.from_location_id)
    db.add(ApprovalRecord(subject_type="transfer", subject_id=transfer.id,
                          decision="approved" if body.approve else "rejected", decided_by=user.id, reason=body.note))
    audit(db, user, "stock.transfer_decision", "inventory_transfer", transfer.id, {"status": "requested"},
          {"status": transfer.status})
    db.commit()
    return _transfer_dict(db, transfer)


def _count_dict(db: Session, count: InventoryCount) -> dict:
    lines = db.scalars(select(InventoryCountLine).where(InventoryCountLine.count_id == count.id))
    return {**row(count, "id", "location_id", "counted_at", "counted_by", "status", "month"),
            "lines": [{**row(ln, "item_id", "system_qty", "counted_qty", "adjustment_txn_id", "reason"),
                       "variance": ln.counted_qty - ln.system_qty} for ln in lines]}


def _over_received_message(item: InventoryItem, counted: int, limit: int, parts: dict | None) -> str:
    detail = f" (invoices {parts['invoices']}, opening stock {parts['opening']}, transfers in {parts['transfers_in']})" if parts else ""
    return (f"{item.name}: counted {counted} is more than the {limit} received into this location{detail}. "
            "Something is wrong: check the count, then the receipts and opening stock.")


def _alert_over_received(db: Session, user: User, location: Location, item: InventoryItem, counted: int, limit: int, parts: dict | None) -> None:
    """A count higher than everything received is refused, but supervisors and managers are told and it is kept in the audit log."""
    notify(db, recipients(db, location.id, SUPERVISOR, MANAGER), "count_over_received",
           f"Count higher than received at {location.name}: {item.name} counted {counted}, received {limit}",
           key=f"countover:{location.id}:{item.id}:{user.id}:{timeutil.utc_now().isoformat(timespec='minutes')}", priority="critical",
           location_id=location.id, link="/stock-movements", requires_ack=True, body=_over_received_message(item, counted, limit, parts))
    audit(db, user, "stock.count_blocked", "inventory_item", item.id, None, {"location_id": location.id, "counted": counted, "received": limit})
    db.commit()


@router.get("/count-limits")
def count_limits(location_id: int, user: User = Depends(require("inventory.count")), db: Session = Depends(get_db)):
    """For each item at a location: what was received, what the system holds, and how the received figure is made up."""
    check_location(user, db, location_id)
    ids = [i for (i,) in db.execute(select(InventoryItem.id).where(InventoryItem.active.is_(True)))]
    parts = received_breakdown(db, location_id, ids)
    balances = {b.item_id: b.qty for b in db.scalars(select(InventoryBalance).where(InventoryBalance.location_id == location_id))}
    return [{"item_id": i, "received": max(sum(parts[i].values()), 0) if i in parts else 0, "system_qty": balances.get(i, 0),
             **(parts[i] if i in parts else {"invoices": 0, "opening": 0, "transfers_in": 0})} for i in ids]


class DraftEntry(BaseModel):
    qty: str = Field(default="", max_length=12)
    reason: str = Field(default="", max_length=500)


class DraftIn(BaseModel):
    location_id: int
    entries: dict[int, DraftEntry] = Field(default_factory=dict, max_length=5000)


@router.get("/count-draft")
def read_count_draft(location_id: int, user: User = Depends(require("inventory.count")), db: Session = Depends(get_db)):
    """The caller's unfinished count at a location, as saved while they typed."""
    check_location(user, db, location_id)
    draft = db.scalar(select(CountDraft).where(CountDraft.user_id == user.id, CountDraft.location_id == location_id))
    return {"entries": draft.entries if draft else {}, "updated_at": draft.updated_at.isoformat() + "Z" if draft else None}


@router.put("/count-draft")
def save_count_draft(body: DraftIn, user: User = Depends(require("inventory.count")), db: Session = Depends(get_db)):
    check_location(user, db, body.location_id)
    entries = {str(i): e.model_dump() for i, e in body.entries.items() if e.qty.strip() or e.reason.strip()}
    draft = db.scalar(select(CountDraft).where(CountDraft.user_id == user.id, CountDraft.location_id == body.location_id))
    if not entries:
        if draft:
            db.delete(draft)
    elif draft:
        draft.entries, draft.updated_at = entries, timeutil.utc_now()
    else:
        db.add(CountDraft(user_id=user.id, location_id=body.location_id, entries=entries, updated_at=timeutil.utc_now()))
    db.commit()
    return {"saved": len(entries)}


@router.post("/counts", status_code=201)
def create_count(body: CountIn, user: User = Depends(require("inventory.count")), db: Session = Depends(get_db)):
    check_location(user, db, body.location_id)
    location = db.get(Location, body.location_id)
    if len({ln.item_id for ln in body.lines}) != len(body.lines):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Each item can be counted once")
    # A count can find less than the book figure and never more than what was received here; more than the book figure needs a reason.
    ids = [ln.item_id for ln in body.lines]
    received, parts = received_to_date(db, location.id, ids), received_breakdown(db, location.id, ids)
    items, surplus = {}, []
    for ln in body.lines:
        items[ln.item_id] = item = get_item_or_404(db, ln.item_id)
        limit = received.get(item.id, 0)
        if ln.counted_qty > limit:
            _alert_over_received(db, user, location, item, ln.counted_qty, limit, parts.get(item.id))
            raise HTTPException(status.HTTP_400_BAD_REQUEST, _over_received_message(item, ln.counted_qty, limit, parts.get(item.id)))
        book = db.get(InventoryBalance, (item.id, location.id))
        if ln.counted_qty > (book.qty if book else 0):
            if not (ln.reason and len(ln.reason.strip()) >= 5):
                raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                    f"{item.name}: counted {ln.counted_qty} is more than the {book.qty if book else 0} the system holds. "
                                    "Give a reason of at least 5 characters, for example an issue that was posted twice.")
            surplus.append((item, ln.counted_qty, book.qty if book else 0))
    now = timeutil.utc_now()
    count = InventoryCount(location_id=location.id, counted_by=user.id, counted_at=now,
                           month=timeutil.to_local(now, location.timezone).strftime("%Y-%m"))
    db.add(count)
    db.flush()
    for ln in body.lines:
        item = items[ln.item_id]
        balance = db.get(InventoryBalance, (item.id, location.id))
        db.add(InventoryCountLine(count_id=count.id, item_id=item.id, system_qty=balance.qty if balance else 0,
                                  counted_qty=ln.counted_qty, reason=ln.reason.strip() if ln.reason else None))
    for item, counted, book in surplus:
        notify(db, recipients(db, location.id, SUPERVISOR, MANAGER), "count_surplus",
               f"Count surplus at {location.name}: {item.name} counted {counted}, system {book}",
               key=f"surplus:{count.id}:{item.id}", priority="high", location_id=location.id, link="/stock-movements", requires_ack=True,
               body=f"Counted by {user.email}. A manager decides whether to post it.")
    draft = db.scalar(select(CountDraft).where(CountDraft.user_id == user.id, CountDraft.location_id == location.id))
    if draft:
        db.delete(draft)  # the count is saved properly, so the working copy is done with
    db.commit()
    return _count_dict(db, count)


@router.get("/counts")
def list_counts(location_id: int | None = None, user: User = Depends(require("inventory.count")),
                db: Session = Depends(get_db)):
    stmt = select(InventoryCount)
    scope = scoped_locations(user, db)
    if location_id is not None:
        check_location(user, db, location_id)
        stmt = stmt.where(InventoryCount.location_id == location_id)
    elif scope is not None:
        stmt = stmt.where(InventoryCount.location_id.in_(scope))
    return [_count_dict(db, c) for c in db.scalars(stmt.order_by(InventoryCount.id.desc()).limit(50))]


@router.post("/counts/{count_id}/post")
def post_count(count_id: int, user: User = Depends(require("inventory.count")), db: Session = Depends(get_db)):
    count = db.get(InventoryCount, count_id)
    if not count:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Count not found")
    check_location(user, db, count.location_id)
    if count.status == "posted":
        raise HTTPException(status.HTTP_409_CONFLICT, "Count was already posted")
    lines = db.scalars(select(InventoryCountLine).where(InventoryCountLine.count_id == count.id)).all()
    received = received_to_date(db, count.location_id, [ln.item_id for ln in lines])
    for ln in lines:
        if ln.counted_qty > received.get(ln.item_id, 0):
            raise HTTPException(status.HTTP_409_CONFLICT, f"{db.get(InventoryItem, ln.item_id).name}: the count is now higher than what was received. "
                                "A receipt may have been voided; recount the item.")
    variances = [ln for ln in lines if ln.counted_qty != ln.system_qty]
    if variances and "stock.approve" not in permissions_of(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a manager can post a count that has variances")
    for ln in variances:
        newer = db.scalar(
            select(InventoryCount.id).join(InventoryCountLine, InventoryCountLine.count_id == InventoryCount.id)
            .join(StockTransaction, StockTransaction.id == InventoryCountLine.adjustment_txn_id)
            .where(InventoryCount.location_id == count.location_id, InventoryCount.id != count.id,
                   InventoryCountLine.item_id == ln.item_id, StockTransaction.occurred_at >= count.counted_at).limit(1))
        if newer:
            raise HTTPException(status.HTTP_409_CONFLICT, f"{db.get(InventoryItem, ln.item_id).name} was already corrected by count #{newer} "
                                "after this count was taken. Recount the item.")
    for ln in variances:
        item = db.get(InventoryItem, ln.item_id)
        txn = post_txn(db, user, item, count.location_id, "adjustment", ln.counted_qty - ln.system_qty,
                       f"Physical count #{count.id} variance", "count", count.id, allow_negative=True)
        ln.adjustment_txn_id = txn.id
    count.status = "posted"
    audit(db, user, "stock.count_post", "inventory_count", count.id, None,
          {"variances": [{"item_id": ln.item_id, "delta": ln.counted_qty - ln.system_qty} for ln in variances]})
    db.commit()
    return _count_dict(db, count)


@router.get("/insights")
def insights(location_id: int | None = None, date_from: date | None = None, date_to: date | None = None,
             date_by: Literal["invoice", "received"] = "invoice",
             user: User = Depends(require("inventory.module")), db: Session = Depends(get_db)):
    """Stock in and out, breakage and transfers for charts; the last 30 days unless dates are given.

    Deliveries sit on the invoice date (or the received date when `date_by` says so), not on the day they were entered."""
    return _insights_with(metrics.stock_insights, location_id, date_from, date_to, date_by, user, db)


@router.get("/analysis")
def analysis(location_id: int | None = None, date_from: date | None = None, date_to: date | None = None,
             date_by: Literal["invoice", "received"] = "invoice",
             user: User = Depends(require("inventory.module")), db: Session = Depends(get_db)):
    """Purchases, suppliers, most used items and what stock is worth, for the same places and dates as the insights."""
    return _insights_with(metrics.stock_analysis, location_id, date_from, date_to, date_by, user, db)


def _insights_with(build, location_id, date_from, date_to, date_by, user, db):
    now = timeutil.utc_now()
    if location_id is not None:
        check_location(user, db, location_id)
    scope = scoped_locations(user, db)
    first = metrics.windows_by(db, now, scope, location_id, lambda t: (t, t))
    if not first:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No locations in scope")
    day_to = date_to or first[0].today
    day_from = date_from or day_to - timedelta(days=29)
    try:
        wins = metrics.windows(db, now, scope, location_id, day_from, day_to)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    return build(db, wins, day_from, day_to, date_by)


def _locations_in_scope(db: Session, user: User) -> list[Location]:
    scope = scoped_locations(user, db)
    stmt = select(Location).where(Location.active.is_(True)).order_by(Location.name)
    return list(db.scalars(stmt.where(Location.id.in_(scope)) if scope is not None else stmt))


@router.get("/cost-report")
def stock_cost(date_from: date, date_to: date, location_id: int | None = None,
               user: User = Depends(require("inventory.module")), db: Session = Depends(get_db)):
    """Opening value, purchases, closing value and cost consumed for a period, at weighted average cost; all locations when none is chosen."""
    if date_to < date_from or (date_to - date_from).days >= 731:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Choose a period of at most two years that ends after it starts")
    if location_id is not None:
        check_location(user, db, location_id)
    places = [db.get(Location, location_id)] if location_id is not None else _locations_in_scope(db, user)
    per_place = []
    for location in places:
        start = timeutil.local_to_utc(date_from, time(0), location.timezone)
        end = timeutil.local_to_utc(date_to + timedelta(days=1), time(0), location.timezone)
        per_place.append({"location_id": location.id, "location": location.name, **cost_report(db, location.id, start, end)})
    period = {"from": date_from.isoformat(), "to": date_to.isoformat()}
    if location_id is not None:
        return {**period, **per_place[0]}
    together: dict[str, dict] = defaultdict(lambda: defaultdict(Decimal))
    for place in per_place:
        for line in place["by_category"]:
            together[line["category"]]["items"] += line["items"]
            for key in MEASURES:
                together[line["category"]][key] += Decimal(str(line[key]))
    totals = {key: round(sum(p["totals"].get(key, 0) for p in per_place), 3) for key in MEASURES}
    return {**period, "locations": per_place, "totals": totals, "by_category": category_rows(together, Decimal(str(totals["cost_consumed"])))}


@router.get("/reconciliation")
def reconciliation(month: str, location_id: int | None = None,
                   user: User = Depends(require("inventory.module")), db: Session = Depends(get_db)):
    """One location, or every location in scope as separate sections with consolidated totals; nothing here changes stock."""
    if not MONTH_RE.match(month):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "month must be YYYY-MM")
    if location_id is not None:
        check_location(user, db, location_id)
        rows = reconcile(db, db.get(Location, location_id), month)
        return {"location_id": location_id, "month": month, "rows": rows, "variance": variance_summary(rows),
                "total_closing": sum(r["closing"] for r in rows)}
    sections = []
    for location in _locations_in_scope(db, user):
        rows = reconcile(db, location, month)
        sections.append({"location_id": location.id, "location": location.name, "rows": rows, "variance": variance_summary(rows),
                         "total_closing": sum(r["closing"] for r in rows), "closing_value": round(sum(r["closing_value"] for r in rows), 3)})
    everything = [r for s in sections for r in s["rows"]]
    return {"month": month, "locations": sections, "variance": variance_summary(everything), "total_closing": sum(s["total_closing"] for s in sections),
            "closing_value": round(sum(s["closing_value"] for s in sections), 3)}
