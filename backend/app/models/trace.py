from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, true
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from .core import ts


class FoodItem(Base):
    """A food product that arrives as a lot, with the group that decides its shelf life."""

    __tablename__ = "food_item"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    food_group: Mapped[str] = mapped_column(String(20))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())


class PortionName(Base):
    """A name a cut of food is portioned under, optionally tied to the food item it comes from."""

    __tablename__ = "portion_name"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    food_item_id: Mapped[int | None] = mapped_column(ForeignKey("food_item.id"), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())


class ShelfLifeRule(Base):
    """How long a food group keeps in a condition, set by the organization to match local rules."""

    __tablename__ = "shelf_life_rule"
    __table_args__ = (UniqueConstraint("food_group", "condition", name="uq_shelf_life_rule"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    food_group: Mapped[str] = mapped_column(String(20))
    condition: Mapped[str] = mapped_column(String(20))
    hours: Mapped[int] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(String(300))


class Lot(Base):
    """One delivery line or one batch of portions; its code is what labels, forms and traces refer to."""

    __tablename__ = "lot"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(48), unique=True)
    kind: Mapped[str] = mapped_column(String(10))  # received | portion
    food_item_id: Mapped[int] = mapped_column(ForeignKey("food_item.id"), index=True)
    food_group: Mapped[str] = mapped_column(String(20), index=True)
    condition: Mapped[str] = mapped_column(String(20))  # chilled_raw | vacuum_chilled | frozen | thawed | cooked_chilled
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("supplier.id"))
    supplier_lot: Mapped[str | None] = mapped_column(String(60))
    produced_on: Mapped[date | None] = mapped_column(Date)
    expiry_on: Mapped[date | None] = mapped_column(Date)
    use_by: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    temp_c: Mapped[Decimal | None] = mapped_column(Numeric(5, 1))
    qty: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    unit: Mapped[str | None] = mapped_column(String(20))
    waste_qty: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))  # trim and loss from cutting this lot, in the same unit as qty
    pack_count: Mapped[int | None] = mapped_column(Integer)
    pack_description: Mapped[str | None] = mapped_column(String(120))
    tag_number: Mapped[str | None] = mapped_column(String(60))  # shellfish or other tag
    location_id: Mapped[int] = mapped_column(ForeignKey("location.id"), index=True)
    status: Mapped[str] = mapped_column(String(12), default="active", index=True)  # active | used_up | discarded | on_hold
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int] = mapped_column(ForeignKey("user.id"))
    created_at: Mapped[datetime] = ts(index=True)
    thawed_at: Mapped[datetime | None] = mapped_column(DateTime)  # set once, when a frozen lot is thawed
    thawed_by: Mapped[int | None] = mapped_column(ForeignKey("user.id"))


class LotLink(Base):
    """A lot made from another: the parent's identity travels with every child."""

    __tablename__ = "lot_link"
    parent_id: Mapped[int] = mapped_column(ForeignKey("lot.id"), primary_key=True)
    child_id: Mapped[int] = mapped_column(ForeignKey("lot.id"), primary_key=True, index=True)


class LotEvent(Base):
    """A change to a lot that its fields alone would not show: status, use-by or a note."""

    __tablename__ = "lot_event"
    id: Mapped[int] = mapped_column(primary_key=True)
    lot_id: Mapped[int] = mapped_column(ForeignKey("lot.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    detail: Mapped[str] = mapped_column(String(300))
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    at: Mapped[datetime] = ts()


class ReadingLot(Base):
    """The lots a monitoring reading used, so a cooking record can be traced back and forward."""

    __tablename__ = "reading_lot"
    reading_id: Mapped[int] = mapped_column(ForeignKey("temperature_reading.id"), primary_key=True)
    lot_id: Mapped[int] = mapped_column(ForeignKey("lot.id"), primary_key=True, index=True)


class LabelPrinter(Base):
    """A network label printer the server prints to directly, set up by a manager."""

    __tablename__ = "label_printer"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60), unique=True)
    host: Mapped[str] = mapped_column(String(120))
    port: Mapped[int] = mapped_column(Integer, default=9100)
    dpi: Mapped[int] = mapped_column(Integer, default=203)
    location_id: Mapped[int | None] = mapped_column(ForeignKey("location.id"))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
