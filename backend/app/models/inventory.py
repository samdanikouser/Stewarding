from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, event, text
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from .core import ts


class InventoryCategory(Base):
    __tablename__ = "inventory_category"
    __table_args__ = (UniqueConstraint("name", name="uq_inventory_category_name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class InventoryUnit(Base):
    __tablename__ = "inventory_unit"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(30), unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Supplier(Base):
    __tablename__ = "supplier"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    name_key: Mapped[str] = mapped_column(String(120), unique=True)  # lower-cased name, blocks case-only duplicates
    contact: Mapped[str | None] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(40))
    email: Mapped[str | None] = mapped_column(String(200))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class InventoryItem(Base):
    __tablename__ = "inventory_item"
    # one item master entry per normalised name
    __table_args__ = (UniqueConstraint("name_key", name="uq_inventory_item_name_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("inventory_category.id"))
    unit_id: Mapped[int] = mapped_column(ForeignKey("inventory_unit.id"))
    description: Mapped[str | None] = mapped_column(Text)
    image_path: Mapped[str | None] = mapped_column(String(300))
    storage_location: Mapped[str | None] = mapped_column(String(80))
    min_level: Mapped[int] = mapped_column(Integer, default=0)
    target_level: Mapped[int | None] = mapped_column(Integer)
    opening_qty: Mapped[int] = mapped_column(Integer, default=0)
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("supplier.id"), index=True)
    name_key: Mapped[str] = mapped_column(String(120), default="", index=True)  # normalised name for duplicate checks
    compact_key: Mapped[str] = mapped_column(String(120), default="", index=True)  # letters and digits only, set from the name
    token_key: Mapped[str] = mapped_column(String(200), default="", index=True)  # sorted singular words, set from the name
    is_tracked_asset: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class InventoryBalance(Base):
    """Derived from stock_transaction and only changed in the same transaction as one."""

    __tablename__ = "inventory_balance"
    item_id: Mapped[int] = mapped_column(ForeignKey("inventory_item.id"), primary_key=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("location.id"), primary_key=True)
    qty: Mapped[int] = mapped_column(Integer, default=0)
    avg_cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))  # weighted average cost per unit at this location


class InventoryLevel(Base):
    """A minimum for one item at one location; where there is no row the item's own minimum applies."""

    __tablename__ = "inventory_level"
    item_id: Mapped[int] = mapped_column(ForeignKey("inventory_item.id"), primary_key=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("location.id"), primary_key=True)
    min_level: Mapped[int] = mapped_column(Integer)


class StockTransaction(Base):
    __tablename__ = "stock_transaction"
    # location and time range reads (reconciliation, movement reports, dashboard charts) use this one index
    __table_args__ = (Index("ix_stock_transaction_location_time_item", "location_id", "occurred_at", "item_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("inventory_item.id"), index=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("location.id"), index=True)
    # opening | receipt | issue | transfer_in | transfer_out | return | damage | breakage | adjustment
    txn_type: Mapped[str] = mapped_column(String(20), index=True)
    qty_delta: Mapped[int] = mapped_column(Integer)
    occurred_at: Mapped[datetime] = ts(index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    reason: Mapped[str | None] = mapped_column(Text)
    ref_type: Mapped[str | None] = mapped_column(String(30))
    ref_id: Mapped[int | None] = mapped_column(Integer)
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))  # cost per unit this movement was valued at (weighted average)


@event.listens_for(StockTransaction, "before_update")
@event.listens_for(StockTransaction, "before_delete")
def _immutable(*_):
    raise ValueError("Stock transactions are immutable; post an adjustment instead")


class StockSnapshot(Base):
    """The closing quantity of an item at a location at the end of a month; a copy rebuilt from the ledger, never a source."""

    __tablename__ = "stock_snapshot"
    __table_args__ = (UniqueConstraint("location_id", "month", "item_id", name="uq_stock_snapshot"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("location.id"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("inventory_item.id"))
    month: Mapped[str] = mapped_column(String(7))  # YYYY-MM in the location's time zone
    qty: Mapped[int] = mapped_column(Integer)
    value: Mapped[Decimal | None] = mapped_column(Numeric(16, 4))  # stock value at the month end
    built_at: Mapped[datetime] = ts()


class InventoryCount(Base):
    __tablename__ = "inventory_count"
    id: Mapped[int] = mapped_column(primary_key=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("location.id"), index=True)
    counted_at: Mapped[datetime] = ts()
    counted_by: Mapped[int] = mapped_column(ForeignKey("user.id"))
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | posted
    month: Mapped[str | None] = mapped_column(String(7))  # YYYY-MM for reconciliation


class ItemSupplier(Base):
    """A supplier an item is also bought from, besides its preferred one; filled by hand and learned from posted invoices."""

    __tablename__ = "item_supplier"
    item_id: Mapped[int] = mapped_column(ForeignKey("inventory_item.id"), primary_key=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("supplier.id"), primary_key=True, index=True)


class CountRound(Base):
    """A stock count over every location, done over a day or two and checked as one pool before anything is posted."""

    __tablename__ = "count_round"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), default="counting", index=True)  # counting | posted | cancelled
    home_location_id: Mapped[int | None] = mapped_column(ForeignKey("location.id"))  # no longer used: stock is placed from what the books hold
    baseline: Mapped[bool] = mapped_column(Boolean, default=False)  # the first round: the gap is the starting point, not a cost
    deadline: Mapped[date | None] = mapped_column(Date)
    created_by: Mapped[int] = mapped_column(ForeignKey("user.id"))
    created_at: Mapped[datetime] = ts()
    posted_by: Mapped[int | None] = mapped_column(ForeignKey("user.id"))
    posted_at: Mapped[datetime | None] = mapped_column(DateTime)
    note: Mapped[str | None] = mapped_column(Text)


class RoundCount(Base):
    """One location's part of a round."""

    __tablename__ = "round_count"
    __table_args__ = (UniqueConstraint("round_id", "location_id", name="uq_round_count_location"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    round_id: Mapped[int] = mapped_column(ForeignKey("count_round.id"), index=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("location.id"))
    status: Mapped[str] = mapped_column(String(20), default="counting")  # counting | done
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("user.id"))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)
    done_at: Mapped[datetime | None] = mapped_column(DateTime)


class RoundCountLine(Base):
    __tablename__ = "round_count_line"
    __table_args__ = (UniqueConstraint("round_count_id", "item_id", name="uq_round_count_line_item"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    round_count_id: Mapped[int] = mapped_column(ForeignKey("round_count.id"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("inventory_item.id"), index=True)
    qty: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(Text)  # why the pool total is above what the books hold


class RoundReview(Base):
    """A manager's decision on one item's unaccounted stock in a round."""

    __tablename__ = "round_review"
    __table_args__ = (UniqueConstraint("round_id", "item_id", name="uq_round_review_item"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    round_id: Mapped[int] = mapped_column(ForeignKey("count_round.id"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("inventory_item.id"))
    decision: Mapped[str] = mapped_column(String(20))  # approved | recount
    decided_by: Mapped[int] = mapped_column(ForeignKey("user.id"))
    decided_at: Mapped[datetime] = ts()
    note: Mapped[str | None] = mapped_column(Text)


class CountDraft(Base):
    """A person's unfinished count for one location, saved as they type so it survives leaving the page or changing phone."""

    __tablename__ = "count_draft"
    __table_args__ = (UniqueConstraint("user_id", "location_id", name="uq_count_draft_user_location"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), index=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("location.id"))
    entries: Mapped[dict] = mapped_column(JSON, default=dict)  # item id -> {"qty": "12", "reason": "..."}
    updated_at: Mapped[datetime] = ts()


class InventoryCountLine(Base):
    __tablename__ = "inventory_count_line"
    __table_args__ = (UniqueConstraint("count_id", "item_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    count_id: Mapped[int] = mapped_column(ForeignKey("inventory_count.id"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("inventory_item.id"))
    system_qty: Mapped[int] = mapped_column(Integer)
    counted_qty: Mapped[int] = mapped_column(Integer)
    adjustment_txn_id: Mapped[int | None] = mapped_column(ForeignKey("stock_transaction.id"))
    reason: Mapped[str | None] = mapped_column(Text)  # why a count is higher than the system quantity


class InventoryTransfer(Base):
    __tablename__ = "inventory_transfer"
    id: Mapped[int] = mapped_column(primary_key=True)
    from_location_id: Mapped[int] = mapped_column(ForeignKey("location.id"), index=True)
    to_location_id: Mapped[int] = mapped_column(ForeignKey("location.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="requested", index=True)
    requested_by: Mapped[int] = mapped_column(ForeignKey("user.id"))
    requested_at: Mapped[datetime] = ts()
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("user.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    note: Mapped[str | None] = mapped_column(Text)


class InventoryTransferLine(Base):
    __tablename__ = "inventory_transfer_line"
    id: Mapped[int] = mapped_column(primary_key=True)
    transfer_id: Mapped[int] = mapped_column(ForeignKey("inventory_transfer.id"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("inventory_item.id"))
    qty: Mapped[int] = mapped_column(Integer)
    asset_ids: Mapped[list[int] | None] = mapped_column(JSON)  # the tracked assets that move with this line


class TrackedAsset(Base):
    __tablename__ = "tracked_asset"
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("inventory_item.id"), index=True)
    asset_tag: Mapped[str] = mapped_column(String(40), unique=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("location.id"))
    condition: Mapped[str] = mapped_column(String(20), default="good")
    custodian_employee_id: Mapped[int | None] = mapped_column(ForeignKey("employee.id"))


class Receipt(Base):
    """A goods receipt or return-to-supplier document; posting it writes ledger rows referencing it."""

    __tablename__ = "receipt"
    # the same supplier invoice cannot be posted twice; a voided receipt frees its number for correct re-entry
    __table_args__ = (Index("uq_receipt_supplier_invoice", "supplier_id", "invoice_number", unique=True,
                            sqlite_where=text("status = 'posted'"), postgresql_where=text("status = 'posted'")),)
    id: Mapped[int] = mapped_column(primary_key=True)
    doc_type: Mapped[str] = mapped_column(String(20), default="receipt")  # receipt | supplier_return
    supplier_id: Mapped[int] = mapped_column(ForeignKey("supplier.id"), index=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("location.id"), index=True)
    invoice_number: Mapped[str] = mapped_column(String(60))
    invoice_date: Mapped[datetime | None] = mapped_column(DateTime)
    received_at: Mapped[datetime] = ts(index=True)  # when the document was entered; the ledger rows carry the same moment
    received_on: Mapped[date | None] = mapped_column(Date)  # the day the goods physically arrived, as the person entered it
    received_by: Mapped[int] = mapped_column(ForeignKey("user.id"))
    note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="posted")  # posted | void
    subtotal: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))  # quantity x unit cost before any discount
    line_discount_total: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    discount_type: Mapped[str | None] = mapped_column(String(10))  # amount | percent, as entered for the whole document
    discount_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    discount_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))  # document discount in money
    total: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))  # subtotal less every discount
    voided_by: Mapped[int | None] = mapped_column(ForeignKey("user.id"))
    voided_at: Mapped[datetime | None] = mapped_column(DateTime)
    void_reason: Mapped[str | None] = mapped_column(Text)


class ReceiptLine(Base):
    __tablename__ = "receipt_line"
    id: Mapped[int] = mapped_column(primary_key=True)
    receipt_id: Mapped[int] = mapped_column(ForeignKey("receipt.id"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("inventory_item.id"), index=True)
    qty: Mapped[int] = mapped_column(Integer)
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    discount_type: Mapped[str | None] = mapped_column(String(10))
    discount_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    discount_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    line_total: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))  # quantity x unit cost less the line discount
    transaction_id: Mapped[int | None] = mapped_column(ForeignKey("stock_transaction.id"), unique=True)
