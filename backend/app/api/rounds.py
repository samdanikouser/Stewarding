"""Count rounds: every location is counted over a day or two, the counts are checked together as one pool against what was received,
and a manager approves the unaccounted stock before the stock is written to match."""
import csv
import io
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import timeutil
from ..audit import audit
from ..db import get_db
from ..deps import check_location, permissions_of, require, scoped_locations
from ..models import (CountRound, InventoryBalance, InventoryCategory, InventoryItem, InventoryUnit, Location, RoundCount, RoundCountLine,
                      RoundReview, StockTransaction, User)
from ..permissions import MANAGER, SUPERVISOR
from ..services.inventory import StockError, post_txn
from ..services.notify import holders_of, notify, recipients
from ..services.settings import get_setting

router = APIRouter(prefix="/api/rounds", tags=["count rounds"])

REASON_MIN = 5


class RoundIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    deadline: date | None = None
    note: str | None = Field(default=None, max_length=500)


class PostIn(BaseModel):
    baseline: bool | None = None  # first round only: accept the gap as the starting point (true) or charge it as usage (false)


class EntryIn(BaseModel):
    qty: str = Field(default="", max_length=12)
    reason: str = Field(default="", max_length=500)


class CountsIn(BaseModel):
    entries: dict[int, EntryIn] = Field(default_factory=dict, max_length=20000)


class ItemsIn(BaseModel):
    item_ids: list[int] = Field(default_factory=list, max_length=20000)
    within_tolerance: bool = False
    note: str | None = Field(default=None, max_length=500)


# ---- the pool ----------------------------------------------------------------------------------------------------

def pool_ceiling(db: Session) -> dict[int, int]:
    """Per item: everything that came in (opening stock, invoices net of voids and supplier returns) less breakage and write-offs.
    Moving stock between locations does not change it, which is what makes it the limit for the counts added together."""
    rows = db.execute(select(StockTransaction.item_id, func.sum(StockTransaction.qty_delta)).where(or_(
        StockTransaction.txn_type == "opening", StockTransaction.ref_type.in_(("receipt", "receipt_void", "breakage")))).group_by(StockTransaction.item_id))
    return {item_id: max(int(total or 0), 0) for item_id, total in rows}


def count_limit(db: Session, round_: CountRound) -> dict[int, int]:
    """The most an item can be counted at in all: what the books hold across the round's locations right now.

    That is everything that came in less everything that left or was written off, in earlier rounds as much as in breakage, so it cannot
    grow back by itself. Stock that turns up after being written off has to be recorded first (a manager's "found stock" adjustment)."""
    places = list(round_places(db, round_))
    held: dict[int, int] = {}
    for b in db.scalars(select(InventoryBalance).where(InventoryBalance.location_id.in_(places or [0]))):
        held[b.item_id] = held.get(b.item_id, 0) + b.qty
    return {item_id: max(qty, 0) for item_id, qty in held.items()}


def pool_book(db: Session) -> tuple[dict[int, int], dict[int, dict[int, int]], dict[int, Decimal]]:
    """Per item: the quantity the books hold across all locations, per location, and the average cost of what is held."""
    book: dict[int, int] = {}
    where: dict[int, dict[int, int]] = {}
    worth: dict[int, Decimal] = {}
    held: dict[int, int] = {}
    items = {i.id: i for i in db.scalars(select(InventoryItem))}
    for b in db.scalars(select(InventoryBalance)):
        book[b.item_id] = book.get(b.item_id, 0) + b.qty
        where.setdefault(b.item_id, {})[b.location_id] = b.qty
        cost = b.avg_cost if b.avg_cost is not None else items[b.item_id].unit_cost
        if cost is not None and b.qty > 0:
            worth[b.item_id] = worth.get(b.item_id, Decimal(0)) + b.qty * Decimal(cost)
            held[b.item_id] = held.get(b.item_id, 0) + b.qty
    average = {i: (worth[i] / held[i]).quantize(Decimal("0.0001")) for i in worth if held.get(i)}
    for item_id, item in items.items():
        if item_id not in average and item.unit_cost is not None:
            average[item_id] = Decimal(item.unit_cost)
    return book, where, average


ROUND_REFS = ("count_round", "count_baseline")


def movements_after(db: Session, round_: CountRound) -> dict[int, dict[int, int]]:
    """Per item and location: stock that moved after that location finished counting (a delivery, an issue, breakage).

    The count did not see it, so it is not a gap, and posting keeps it instead of writing it off."""
    out: dict[int, dict[int, int]] = {}
    for rc in db.scalars(select(RoundCount).where(RoundCount.round_id == round_.id)):
        if not rc.done_at:
            continue
        for item_id, total in db.execute(select(StockTransaction.item_id, func.sum(StockTransaction.qty_delta)).where(
                StockTransaction.location_id == rc.location_id, StockTransaction.occurred_at > rc.done_at,
                or_(StockTransaction.ref_type.is_(None), StockTransaction.ref_type.not_in(ROUND_REFS))).group_by(StockTransaction.item_id)):
            if total:
                out.setdefault(item_id, {})[rc.location_id] = int(total)
    return out


def location_average(db: Session, pool: dict[int, Decimal]) -> dict[tuple[int, int], Decimal]:
    """What each location carries an item at, which is what the ledger uses when it writes stock off or on there; the pool average where it carries none."""
    out: dict[tuple[int, int], Decimal] = {}
    for b in db.scalars(select(InventoryBalance).where(InventoryBalance.avg_cost.is_not(None))):
        out[(b.item_id, b.location_id)] = Decimal(b.avg_cost)
    return {**{(i, 0): c for i, c in pool.items()}, **out}


def allocate(books: dict[int, int], counted: dict[int, int]) -> tuple[list[tuple[int, int, int]], dict[int, int]]:
    """Turns the books into the counts without a designated main store.

    Stock found where the books held less is moved from the places that hold more than they counted (those are the same units, booked in
    another place). Whatever is still left over after that is not in the counts: written off where the books held more than was found, or found
    (a positive adjustment) where more was counted than the books held and nothing else is short."""
    places = sorted(set(books) | set(counted))
    diff = {loc: counted.get(loc, 0) - books.get(loc, 0) for loc in places}
    short = sorted(((loc, -d) for loc, d in diff.items() if d < 0), key=lambda x: (-x[1], x[0]))  # (place, units the books hold beyond the count)
    over = sorted(((loc, d) for loc, d in diff.items() if d > 0), key=lambda x: (-x[1], x[0]))     # (place, units found beyond the books)
    transfers: list[tuple[int, int, int]] = []
    short, over = [list(x) for x in short], [list(x) for x in over]
    i = j = 0
    while i < len(short) and j < len(over):
        move = min(short[i][1], over[j][1])
        transfers.append((short[i][0], over[j][0], move))
        short[i][1] -= move
        over[j][1] -= move
        i += short[i][1] == 0
        j += over[j][1] == 0
    adjust = {loc: -left for loc, left in short if left} | {loc: left for loc, left in over if left}
    return transfers, adjust


def round_places(db: Session, round_: CountRound) -> dict[int, str]:
    """The locations of a round with their names, in name order."""
    names = {loc.id: loc.name for loc in db.scalars(select(Location))}
    ids = [rc.location_id for rc in db.scalars(select(RoundCount).where(RoundCount.round_id == round_.id))]
    return {loc: names.get(loc, str(loc)) for loc in sorted(ids, key=lambda i: names.get(i, ""))}


def _by_location(opening: dict[int, int], counted: dict[int, int], places: dict[int, str]) -> list[dict]:
    """For each location: what the books held when it was counted, what was counted (the closing stock), and the difference."""
    return [{"location": name, "opening": opening.get(loc, 0), "counted": counted.get(loc, 0), "difference": counted.get(loc, 0) - opening.get(loc, 0)}
            for loc, name in places.items() if opening.get(loc, 0) or counted.get(loc, 0)]


def round_counts(db: Session, round_: CountRound) -> tuple[dict[int, dict[int, int]], dict[int, dict[int, str]]]:
    """Per item: what each location counted in this round, and the reasons given."""
    counted: dict[int, dict[int, int]] = {}
    reasons: dict[int, dict[int, str]] = {}
    for loc_id, item_id, qty, reason in db.execute(select(RoundCount.location_id, RoundCountLine.item_id, RoundCountLine.qty, RoundCountLine.reason)
                                                  .join(RoundCountLine, RoundCountLine.round_count_id == RoundCount.id).where(RoundCount.round_id == round_.id)):
        counted.setdefault(item_id, {})[loc_id] = qty
        if reason:
            reasons.setdefault(item_id, {})[loc_id] = reason
    return counted, reasons


def tolerance_for(db: Session, book_total: int) -> float:
    """The most unaccounted stock that is just normal counting error: the larger of a few units or a percentage of what the books hold."""
    return max(get_setting(db, "stock.round_tolerance_units"), book_total * get_setting(db, "stock.round_tolerance_percent") / 100)


def _first_round(db: Session, round_: CountRound) -> bool:
    """Whether no round has been posted before this one, so its gap is the stock that went missing before anything was tracked."""
    return db.scalar(select(CountRound.id).where(CountRound.status == "posted", CountRound.id != round_.id).limit(1)) is None


def _round(db: Session, user: User, round_id: int) -> CountRound:
    found = db.get(CountRound, round_id)
    if not found:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Count round not found")
    return found


def _manager(user: User = Depends(require("stock.approve"))) -> User:
    return user


def _locations(db: Session) -> list[Location]:
    return list(db.scalars(select(Location).where(Location.active.is_(True)).order_by(Location.name)))


# ---- rounds -------------------------------------------------------------------------------------------------------

def _progress(db: Session, round_: CountRound) -> list[dict]:
    names = {loc.id: loc.name for loc in db.scalars(select(Location))}
    lines = dict(db.execute(select(RoundCount.id, func.count(RoundCountLine.id)).outerjoin(RoundCountLine, RoundCountLine.round_count_id == RoundCount.id)
                            .where(RoundCount.round_id == round_.id).group_by(RoundCount.id)).all())
    return [{"location_id": rc.location_id, "location": names.get(rc.location_id), "status": rc.status, "counted_items": lines.get(rc.id, 0),
             "updated_at": rc.updated_at.isoformat() + "Z" if rc.updated_at else None, "done_at": rc.done_at.isoformat() + "Z" if rc.done_at else None}
            for rc in sorted(db.scalars(select(RoundCount).where(RoundCount.round_id == round_.id)), key=lambda r: names.get(r.location_id) or "")]


def _summary(db: Session, round_: CountRound) -> dict:
    return {"id": round_.id, "name": round_.name, "status": round_.status, "baseline": round_.baseline,
            "deadline": round_.deadline.isoformat() if round_.deadline else None, "created_at": round_.created_at.isoformat() + "Z",
            "posted_at": round_.posted_at.isoformat() + "Z" if round_.posted_at else None, "note": round_.note,
            "locations": _progress(db, round_)}


@router.get("")
def list_rounds(user: User = Depends(require("inventory.count")), db: Session = Depends(get_db)):
    return [_summary(db, r) for r in db.scalars(select(CountRound).order_by(CountRound.id.desc()).limit(50))]


@router.post("", status_code=201)
def start_round(body: RoundIn, user: User = Depends(_manager), db: Session = Depends(get_db)):
    if db.scalar(select(CountRound.id).where(CountRound.status == "counting")):
        raise HTTPException(status.HTTP_409_CONFLICT, "A count round is already open. Post or cancel it before starting another")
    round_ = CountRound(name=" ".join(body.name.split()), baseline=False,
                        deadline=body.deadline, created_by=user.id, note=body.note)
    db.add(round_)
    db.flush()
    db.add_all(RoundCount(round_id=round_.id, location_id=loc.id) for loc in _locations(db))
    audit(db, user, "round.start", "count_round", round_.id, None, body.model_dump(mode="json"))
    db.commit()
    return _summary(db, round_)


@router.get("/{round_id}")
def read_round(round_id: int, user: User = Depends(require("inventory.count")), db: Session = Depends(get_db)):
    return _summary(db, _round(db, user, round_id))


@router.post("/{round_id}/cancel")
def cancel_round(round_id: int, user: User = Depends(_manager), db: Session = Depends(get_db)):
    round_ = _round(db, user, round_id)
    if round_.status != "counting":
        raise HTTPException(status.HTTP_409_CONFLICT, f"The round is already {round_.status}")
    round_.status = "cancelled"
    audit(db, user, "round.cancel", "count_round", round_.id, None, None)
    db.commit()
    return _summary(db, round_)


# ---- counting one location --------------------------------------------------------------------------------------

def _round_count(db: Session, user: User, round_: CountRound, location_id: int) -> RoundCount:
    check_location(user, db, location_id)
    found = db.scalar(select(RoundCount).where(RoundCount.round_id == round_.id, RoundCount.location_id == location_id))
    if not found:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That location is not part of this round")
    return found


@router.get("/{round_id}/entry")
def entry_sheet(round_id: int, location_id: int, user: User = Depends(require("inventory.count")), db: Session = Depends(get_db)):
    """What to count at one location: each item in the pool with what others have counted and how much is left to enter."""
    round_ = _round(db, user, round_id)
    rc = _round_count(db, user, round_, location_id)
    ceiling, limit, (book, where, _) = pool_ceiling(db), count_limit(db, round_), pool_book(db)
    counted, reasons = round_counts(db, round_)
    categories = {c.id: c.name for c in db.scalars(select(InventoryCategory))}
    units = {u.id: u.name for u in db.scalars(select(InventoryUnit))}
    out = []
    for item in db.scalars(select(InventoryItem).where(InventoryItem.active.is_(True)).order_by(InventoryItem.code)):
        mine = counted.get(item.id, {}).get(location_id)
        if mine is None and not ceiling.get(item.id) and not book.get(item.id):
            continue  # never received anywhere, so nothing to count
        others = sum(q for loc, q in counted.get(item.id, {}).items() if loc != location_id)
        out.append({"item_id": item.id, "code": item.code, "name": item.name, "image_path": item.image_path, "unit": units.get(item.unit_id), "category": categories.get(item.category_id),
                    "storage_location": item.storage_location, "qty": mine, "reason": reasons.get(item.id, {}).get(location_id, ""),
                    "others": others, "received": ceiling.get(item.id, 0), "book": book.get(item.id, 0), "here": where.get(item.id, {}).get(location_id, 0),
                    "allowance": max(limit.get(item.id, 0) - others, 0)})
    return {"round_id": round_.id, "status": rc.status, "round_status": round_.status, "location_id": location_id, "items": out}


@router.put("/{round_id}/counts/{location_id}")
def save_counts(round_id: int, location_id: int, body: CountsIn, user: User = Depends(require("inventory.count")), db: Session = Depends(get_db)):
    """Saves what has been typed so far. A line that would push the pool total above what was received is refused (the rest are kept)."""
    round_ = _round(db, user, round_id)
    rc = _round_count(db, user, round_, location_id)
    if round_.status != "counting" or rc.status == "done":
        raise HTTPException(status.HTTP_409_CONFLICT, "This count is finished. Reopen it to change a number")
    limit, (book, _, _) = count_limit(db, round_), pool_book(db)
    counted, _ = round_counts(db, round_)
    items = {i.id: i for i in db.scalars(select(InventoryItem).where(InventoryItem.id.in_(list(body.entries) or [0])))}
    have = {ln.item_id: ln for ln in db.scalars(select(RoundCountLine).where(RoundCountLine.round_count_id == rc.id))}
    refused, needs_reason, saved = [], [], 0
    place = db.get(Location, location_id)
    for item_id, entry in body.entries.items():
        item = items.get(item_id)
        text = entry.qty.strip()
        if item is None:
            continue
        if text == "":
            if item_id in have:
                db.delete(have.pop(item_id))
                counted.get(item_id, {}).pop(location_id, None)
            continue
        if not text.isdigit():
            refused.append({"item_id": item_id, "message": "Enter a whole number, zero or more"})
            continue
        qty = int(text)
        others = sum(q for loc, q in counted.get(item_id, {}).items() if loc != location_id)
        if others + qty > limit.get(item_id, 0):
            message = (f"{item.name}: counted {qty} here and {others} elsewhere is {others + qty}, more than the {limit.get(item_id, 0)} the books hold "
                       f"(everything received, less breakage, write-offs and earlier counts). At most {max(limit.get(item_id, 0) - others, 0)} can be entered here. "
                       "Check the count. If the stock really was found, a manager records it as a found-stock adjustment first, then counts again.")
            refused.append({"item_id": item_id, "message": message})
            notify(db, recipients(db, location_id, SUPERVISOR, MANAGER), "count_over_received",
                   f"Count above the books: {item.name} at {place.name} ({others + qty} counted in all, {limit.get(item_id, 0)} held)",
                   key=f"roundover:{round_.id}:{item_id}:{user.id}:{timeutil.utc_now().isoformat(timespec='minutes')}", priority="critical",
                   location_id=location_id, link="/stock-movements?tab=rounds", requires_ack=True, body=message)
            continue
        line = have.get(item_id)
        reason = entry.reason.strip() or None
        if line:
            changed = line.qty != qty
            line.qty, line.reason = qty, reason
        else:
            line = RoundCountLine(round_count_id=rc.id, item_id=item_id, qty=qty, reason=reason)
            db.add(line)
            have[item_id] = line
            changed = True
        counted.setdefault(item_id, {})[location_id] = qty
        if changed:
            db.execute(RoundReview.__table__.delete().where(RoundReview.round_id == round_.id, RoundReview.item_id == item_id))  # a changed number needs looking at again
        saved += 1
    for item_id in {i for i in counted if i in body.entries}:
        if sum(counted[item_id].values()) > book.get(item_id, 0) and len((have.get(item_id).reason or "") if item_id in have else "") < REASON_MIN:
            needs_reason.append(item_id)
    rc.updated_by, rc.updated_at = user.id, timeutil.utc_now()
    db.commit()
    return {"saved": saved, "refused": refused, "needs_reason": needs_reason}


@router.post("/{round_id}/counts/{location_id}/done")
def finish_location(round_id: int, location_id: int, user: User = Depends(require("inventory.count")), db: Session = Depends(get_db)):
    round_ = _round(db, user, round_id)
    rc = _round_count(db, user, round_, location_id)
    if round_.status != "counting":
        raise HTTPException(status.HTTP_409_CONFLICT, f"The round is already {round_.status}")
    book = pool_book(db)[0]
    counted, reasons = round_counts(db, round_)
    missing = [i for i, per in counted.items() if sum(per.values()) > book.get(i, 0) and location_id in per
               and len(reasons.get(i, {}).get(location_id, "")) < REASON_MIN]
    if missing:
        names = {i.id: i.name for i in db.scalars(select(InventoryItem).where(InventoryItem.id.in_(missing)))}
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "These items are counted above what the books hold, so each needs a reason: "
                            + ", ".join(sorted(names.values())[:8]))
    rc.status, rc.done_at, rc.updated_by, rc.updated_at = "done", timeutil.utc_now(), user.id, timeutil.utc_now()
    db.flush()
    if not db.scalar(select(RoundCount.id).where(RoundCount.round_id == round_.id, RoundCount.status != "done")):
        notify(db, holders_of(db, "stock.approve", None), "round_ready", f"Count round '{round_.name}' is ready to review",
               key=f"roundready:{round_.id}:{timeutil.utc_now().isoformat(timespec='minutes')}", priority="high", link="/stock-movements?tab=rounds",
               body="Every location has finished counting. Check the unaccounted stock and approve it.")
    db.commit()
    return _summary(db, round_)


@router.post("/{round_id}/counts/{location_id}/reopen")
def reopen_location(round_id: int, location_id: int, user: User = Depends(require("inventory.count")), db: Session = Depends(get_db)):
    round_ = _round(db, user, round_id)
    rc = _round_count(db, user, round_, location_id)
    if round_.status != "counting":
        raise HTTPException(status.HTTP_409_CONFLICT, f"The round is already {round_.status}")
    rc.status, rc.done_at = "counting", None
    db.commit()
    return _summary(db, round_)


# ---- review ------------------------------------------------------------------------------------------------------

def _gap_value(item_id: int, books: dict[int, int], counted: dict[int, int], average: dict[tuple[int, int], Decimal], pool: dict[int, Decimal]) -> float:
    """What the unaccounted stock is worth: each location's shortfall at the cost it carries the item at, as the ledger will write it."""
    _, adjust = allocate(books, {loc: counted.get(loc, 0) for loc in books})
    return round(float(sum(-qty * average.get((item_id, loc), pool.get(item_id, Decimal(0))) for loc, qty in adjust.items())), 3)


def review_rows(db: Session, round_: CountRound) -> list[dict]:
    """Per item: what the books hold, what was received, what each location counted, and the stock that cannot be accounted for."""
    ceiling, (book, where, pool_average) = pool_ceiling(db), pool_book(db)
    average, later = location_average(db, pool_average), movements_after(db, round_)
    places = round_places(db, round_)
    counted, reasons = round_counts(db, round_)
    decisions = {r.item_id: r for r in db.scalars(select(RoundReview).where(RoundReview.round_id == round_.id))}
    names = {loc.id: loc.name for loc in db.scalars(select(Location))}
    categories = {c.id: c.name for c in db.scalars(select(InventoryCategory))}
    rows = []
    for item in db.scalars(select(InventoryItem).order_by(InventoryItem.code)):
        per = counted.get(item.id, {})
        books_then = {loc: where.get(item.id, {}).get(loc, 0) - later.get(item.id, {}).get(loc, 0) for loc in places}  # what each location's books held when it was counted
        total_book = sum(books_then.values())
        if not total_book and not per and not ceiling.get(item.id):
            continue
        never = not per and total_book > 0  # nobody entered anything for it: skipped, or really all gone
        counted_total = sum(per.values())
        gap = total_book - counted_total
        allowed = tolerance_for(db, total_book)
        decision = decisions.get(item.id)
        rows.append({
            "item_id": item.id, "code": item.code, "name": item.name, "category": categories.get(item.category_id),
            "received": ceiling.get(item.id, 0), "book": total_book, "counted": counted_total,
            "by_location": {names.get(loc, str(loc)): qty for loc, qty in sorted(per.items(), key=lambda kv: names.get(kv[0], ""))},
            "locations": _by_location(books_then, per, places),
            "unaccounted": gap, "value": _gap_value(item.id, books_then, per, average, pool_average), "within_tolerance": abs(gap) <= allowed and not never,
            "tolerance": round(allowed, 1), "reasons": list(reasons.get(item.id, {}).values()), "not_counted": never,
            "decision": decision.decision if decision else None, "note": decision.note if decision else None,
            "state": ("balanced" if gap == 0 else "recount" if decision and decision.decision == "recount" else "approved" if decision and decision.decision == "approved"
                      else "not_counted" if never else "within_tolerance" if abs(gap) <= allowed else "needs_review")})
    return rows


def posted_rows(db: Session, round_: CountRound) -> list[dict]:
    """What a posted round did, from the ledger it wrote: per item, what was counted where and the unaccounted stock that left as usage."""
    adjusted: dict[int, tuple[int, Decimal]] = {}
    for item_id, qty, cost in db.execute(select(StockTransaction.item_id, StockTransaction.qty_delta, StockTransaction.unit_cost).where(
            StockTransaction.ref_type.in_(("count_round", "count_baseline")), StockTransaction.ref_id == round_.id, StockTransaction.txn_type == "adjustment")):
        total, value = adjusted.get(item_id, (0, Decimal(0)))
        adjusted[item_id] = (total + qty, value + qty * Decimal(cost or 0))
    counted, reasons = round_counts(db, round_)
    names = {loc.id: loc.name for loc in db.scalars(select(Location))}
    categories = {c.id: c.name for c in db.scalars(select(InventoryCategory))}
    ceiling = pool_ceiling(db)
    places = round_places(db, round_)
    moved: dict[int, dict[int, int]] = {}  # per item and location: what the round itself changed, so opening = counted - that
    for item_id, loc, total in db.execute(select(StockTransaction.item_id, StockTransaction.location_id, func.sum(StockTransaction.qty_delta)).where(
            StockTransaction.ref_type.in_(("count_round", "count_baseline")), StockTransaction.ref_id == round_.id).group_by(StockTransaction.item_id, StockTransaction.location_id)):
        moved.setdefault(item_id, {})[loc] = int(total or 0)
    rows = []
    for item in db.scalars(select(InventoryItem).where(InventoryItem.id.in_(list(set(adjusted) | set(counted)) or [0])).order_by(InventoryItem.code)):
        per = counted.get(item.id, {})
        counted_total, (change, value) = sum(per.values()), adjusted.get(item.id, (0, Decimal(0)))
        rows.append({"item_id": item.id, "code": item.code, "name": item.name, "category": categories.get(item.category_id), "received": ceiling.get(item.id, 0),
                     "book": counted_total - change, "counted": counted_total,
                     "by_location": {names.get(loc, str(loc)): qty for loc, qty in sorted(per.items(), key=lambda kv: names.get(kv[0], ""))},
                     "locations": _by_location({loc: per.get(loc, 0) - moved.get(item.id, {}).get(loc, 0) for loc in places}, per, places),
                     "unaccounted": -change, "value": round(float(-value), 3), "within_tolerance": False, "tolerance": 0,
                     "reasons": list(reasons.get(item.id, {}).values()), "decision": "approved", "note": None, "state": "balanced" if change == 0 else "approved"})
    return rows


@router.get("/{round_id}/review")
def review(round_id: int, user: User = Depends(require("inventory.count")), db: Session = Depends(get_db)):
    round_ = _round(db, user, round_id)
    rows = posted_rows(db, round_) if round_.status == "posted" else review_rows(db, round_)
    states: dict[str, int] = {}
    for r in rows:
        states[r["state"]] = states.get(r["state"], 0) + 1
    gaps = [r for r in rows if r["unaccounted"]]
    return {"round": _summary(db, round_), "first_round": _first_round(db, round_), "rows": rows, "states": states,
            "shortage_value": round(sum(r["value"] for r in gaps if r["unaccounted"] > 0), 3),
            "surplus_value": round(-sum(r["value"] for r in gaps if r["unaccounted"] < 0), 3)}


def _decide(db: Session, user: User, round_: CountRound, item_ids: list[int], decision: str, note: str | None) -> int:
    for item_id in item_ids:
        row = db.scalar(select(RoundReview).where(RoundReview.round_id == round_.id, RoundReview.item_id == item_id))
        if row:
            row.decision, row.decided_by, row.decided_at, row.note = decision, user.id, timeutil.utc_now(), note
        else:
            db.add(RoundReview(round_id=round_.id, item_id=item_id, decision=decision, decided_by=user.id, note=note))
    return len(item_ids)


@router.post("/{round_id}/approve")
def approve_items(round_id: int, body: ItemsIn, user: User = Depends(_manager), db: Session = Depends(get_db)):
    """Approves the unaccounted stock of the chosen items, or of every item within the tolerance."""
    round_ = _round(db, user, round_id)
    if round_.status != "counting":
        raise HTTPException(status.HTTP_409_CONFLICT, f"The round is already {round_.status}")
    rows = review_rows(db, round_)
    chosen = [r["item_id"] for r in rows if r["unaccounted"] and (r["item_id"] in body.item_ids or (body.within_tolerance and r["within_tolerance"]))
              and r["decision"] != "approved"]
    count = _decide(db, user, round_, chosen, "approved", body.note)
    audit(db, user, "round.approve", "count_round", round_.id, None, {"items": count, "within_tolerance": body.within_tolerance})
    db.commit()
    return {"approved": count}


@router.post("/{round_id}/recount")
def ask_recount(round_id: int, body: ItemsIn, user: User = Depends(_manager), db: Session = Depends(get_db)):
    """Sends items back to be counted again: every location is reopened so the numbers can be corrected."""
    round_ = _round(db, user, round_id)
    if round_.status != "counting":
        raise HTTPException(status.HTTP_409_CONFLICT, f"The round is already {round_.status}")
    if not body.item_ids:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Choose the items to count again")
    count = _decide(db, user, round_, body.item_ids, "recount", body.note)
    for rc in db.scalars(select(RoundCount).where(RoundCount.round_id == round_.id)):
        rc.status, rc.done_at = "counting", None
    audit(db, user, "round.recount", "count_round", round_.id, None, {"items": body.item_ids, "note": body.note})
    db.commit()
    return {"recount": count}


# ---- posting ------------------------------------------------------------------------------------------------------

@router.post("/{round_id}/post")
def post_round(round_id: int, body: PostIn | None = None, user: User = Depends(_manager), db: Session = Depends(get_db)):
    """Writes the stock to match the counts: allocations to the outlets, the main store set to its own count, and the rest as usage."""
    round_ = _round(db, user, round_id)
    if round_.status != "counting":
        raise HTTPException(status.HTTP_409_CONFLICT, f"The round is already {round_.status}")
    waiting = [p["location"] for p in _progress(db, round_) if p["status"] != "done"]
    if waiting:
        raise HTTPException(status.HTTP_409_CONFLICT, "These locations have not finished counting: " + ", ".join(waiting))
    wants_baseline = bool(body and body.baseline)
    if wants_baseline and not _first_round(db, round_):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only the first round can take its gap as the starting point; later rounds charge it as usage")
    round_.baseline = wants_baseline
    rows = review_rows(db, round_)
    open_items = [r["name"] for r in rows if r["unaccounted"] and r["state"] != "approved"]
    if open_items:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{len(open_items)} item(s) still have unaccounted stock that is not approved: " + ", ".join(open_items[:6]))
    counted, _ = round_counts(db, round_)
    later = movements_after(db, round_)
    items = {i.id: i for i in db.scalars(select(InventoryItem))}
    locations = [rc.location_id for rc in db.scalars(select(RoundCount).where(RoundCount.round_id == round_.id))]  # only the places that were counted
    stamp = max((rc.done_at for rc in db.scalars(select(RoundCount).where(RoundCount.round_id == round_.id)) if rc.done_at), default=timeutil.utc_now())
    reason = f"Count round '{round_.name}'"
    ref_adjust = "count_baseline" if round_.baseline else "count_round"
    posted = {"items": 0, "usage_value": Decimal(0), "surplus_value": Decimal(0)}
    average = location_average(db, pool_book(db)[2])
    balances: dict[int, dict[int, int]] = {}
    for b in db.scalars(select(InventoryBalance)):
        balances.setdefault(b.item_id, {})[b.location_id] = b.qty
    try:
        for row in rows:
            item = items[row["item_id"]]
            kept = later.get(item.id, {})  # movements after a location's count stay on top of what it counted
            books = {loc: balances.get(item.id, {}).get(loc, 0) - kept.get(loc, 0) for loc in locations}
            transfers, adjust = allocate(books, {loc: counted.get(item.id, {}).get(loc, 0) for loc in locations})
            if not transfers and not adjust:
                continue
            for src, dst, qty in transfers:  # the same units, booked in another place, move to where they were found
                sent = post_txn(db, user, item, src, "transfer_out", qty, reason, "count_round", round_.id, allow_negative=True, occurred_at=stamp)
                post_txn(db, user, item, dst, "transfer_in", qty, reason, "count_round", round_.id, unit_cost=sent.unit_cost, allow_negative=True, occurred_at=stamp)
            for loc, qty in adjust.items():  # and what is left over was used, lost, or found
                post_txn(db, user, item, loc, "adjustment", qty, reason + (": accepted as the starting point" if round_.baseline else ": unaccounted stock approved"),
                         ref_adjust, round_.id, allow_negative=True, occurred_at=stamp)
                value = -qty * average.get((item.id, loc), Decimal(0))
                posted["usage_value" if value > 0 else "surplus_value"] += abs(value)
            posted["items"] += 1
    except StockError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    round_.status, round_.posted_by, round_.posted_at = "posted", user.id, timeutil.utc_now()
    audit(db, user, "round.post", "count_round", round_.id, None, {"items": posted["items"], "usage_value": str(posted["usage_value"]), "baseline": round_.baseline})
    db.commit()
    return {**_summary(db, round_), "posted_items": posted["items"], "usage_value": round(float(posted["usage_value"]), 3),
            "surplus_value": round(float(posted["surplus_value"]), 3)}


@router.get("/{round_id}/report.csv")
def report(round_id: int, user: User = Depends(_manager), db: Session = Depends(get_db)):
    round_ = _round(db, user, round_id)
    rows = posted_rows(db, round_) if round_.status == "posted" else review_rows(db, round_)
    places = sorted({loc["location"] for r in rows for loc in r["locations"]})
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["Code", "Item", "Category", "Received in all", *[f"{p} {part}" for p in places for part in ("opening", "counted (closing)", "difference")],
                     "Opening total", "Counted total", "Unaccounted", "Value", "Decision"])
    for r in rows:
        by = {loc["location"]: loc for loc in r["locations"]}
        cells = []
        for p in places:
            loc = by.get(p)
            cells += [loc["opening"], loc["counted"], loc["difference"]] if loc else [0, 0, 0]
        writer.writerow([r["code"], r["name"], r["category"], r["received"], *cells, r["book"], r["counted"], r["unaccounted"], r["value"], r["decision"] or ""])
    return Response("﻿" + out.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="count-round-{round_.id}.csv"'})
