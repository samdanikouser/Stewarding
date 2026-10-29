from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from .core import ts


class BreakageIncident(Base):
    __tablename__ = "breakage_incident"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)
    occurred_at: Mapped[datetime] = ts(index=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("location.id"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("inventory_item.id"), index=True)
    qty: Mapped[int] = mapped_column(Integer)
    incident_type: Mapped[str] = mapped_column(String(20))  # breakage | damage | missing | written_off
    reason: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    shift_id: Mapped[int | None] = mapped_column(ForeignKey("shift.id"))
    reported_by: Mapped[int] = mapped_column(ForeignKey("user.id"))
    photo_path: Mapped[str | None] = mapped_column(String(300))
    est_cost: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    status: Mapped[str] = mapped_column(String(20), default="reported", index=True)
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("user.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("user.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    preventive_action: Mapped[str | None] = mapped_column(Text)
    # unique: a breakage can be deducted from stock only once
    transaction_id: Mapped[int | None] = mapped_column(ForeignKey("stock_transaction.id"), unique=True)


class Notification(Base):
    __tablename__ = "notification"
    # one notification per recipient and event window prevents duplicates
    __table_args__ = (UniqueConstraint("user_id", "dedupe_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    priority: Mapped[str] = mapped_column(String(10), default="normal")  # normal | high | critical
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str | None] = mapped_column(Text)
    location_id: Mapped[int | None] = mapped_column(ForeignKey("location.id"))
    link: Mapped[str | None] = mapped_column(String(200))
    dedupe_key: Mapped[str] = mapped_column(String(120))
    due_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = ts(index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime)
    requires_ack: Mapped[bool] = mapped_column(Boolean, default=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)


class PushSubscription(Base):
    """One browser or phone that asked for push alerts; the endpoint is where the browser's push service takes a message."""

    __tablename__ = "push_subscription"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), index=True)
    endpoint: Mapped[str] = mapped_column(String(600), unique=True)
    p256dh: Mapped[str] = mapped_column(String(200))
    auth: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = ts()


class ApprovalRecord(Base):
    __tablename__ = "approval_record"
    id: Mapped[int] = mapped_column(primary_key=True)
    subject_type: Mapped[str] = mapped_column(String(30), index=True)
    subject_id: Mapped[int] = mapped_column(Integer)
    decision: Mapped[str] = mapped_column(String(20))
    decided_by: Mapped[int] = mapped_column(ForeignKey("user.id"))
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = ts()


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = ts(index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"), index=True)
    action: Mapped[str] = mapped_column(String(60), index=True)
    entity: Mapped[str] = mapped_column(String(40), index=True)
    entity_id: Mapped[int | None] = mapped_column(Integer)
    before: Mapped[dict | None] = mapped_column(JSON)
    after: Mapped[dict | None] = mapped_column(JSON)


class LookupValue(Base):
    """Managed dropdown values (job titles, checklist categories, breakage reasons, standard corrective actions)."""

    __tablename__ = "lookup_value"
    __table_args__ = (UniqueConstraint("kind", "value_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(30), index=True)
    value: Mapped[str] = mapped_column(String(120))
    value_key: Mapped[str] = mapped_column(String(120))  # lower-cased value, blocks case-only duplicates
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Organization(Base):
    """The one organization whose name, details and logo head every report; the row id is always 1."""

    __tablename__ = "organization"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), default="")
    legal_name: Mapped[str | None] = mapped_column(String(160))
    address: Mapped[str | None] = mapped_column(String(500))
    phone: Mapped[str | None] = mapped_column(String(40))
    email: Mapped[str | None] = mapped_column(String(120))
    website: Mapped[str | None] = mapped_column(String(200))
    registration_number: Mapped[str | None] = mapped_column(String(60))
    report_footer: Mapped[str | None] = mapped_column(String(300))
    logo: Mapped[str | None] = mapped_column(String(60))
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kuwait")  # shown on reports and used for new locations
    currency: Mapped[str | None] = mapped_column(String(8))  # shown with amounts; none until set


class ScanEvent(Base):
    """A person scanning the QR code of a monitoring point or a location; recording there can require a recent scan."""

    __tablename__ = "scan_event"
    __table_args__ = (Index("ix_scan_event_lookup", "user_id", "kind", "target_id", "created_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    kind: Mapped[str] = mapped_column(String(12))  # equipment | location
    target_id: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = ts()
