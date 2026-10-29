import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import audit
from ..db import get_db
from ..deps import check_location, permissions_of, require
from ..models import LabelPrinter, User
from ..services import labels
from ..services.printers import PrinterError, private_addresses, send_zpl
from .lots import any_of, label_pages

router = APIRouter(prefix="/api/label-printers", tags=["label printers"])

HOST_RE = re.compile(r"^[A-Za-z0-9._-]+$")
USERS = ("lot.receive", "lot.split", "lot.manage")


class PrinterIn(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    host: str = Field(min_length=3, max_length=120)
    port: int = Field(default=9100, ge=1, le=65535)
    dpi: Literal[203, 300, 600] = 203
    location_id: int | None = None
    active: bool = True

    @field_validator("name")
    @classmethod
    def _tidy(cls, value: str) -> str:
        return " ".join(value.split())

    @field_validator("host")
    @classmethod
    def _plain_host(cls, value: str) -> str:
        value = value.strip()
        if not HOST_RE.fullmatch(value):
            raise ValueError("Enter the printer's IP address or network name, such as 192.168.1.50")
        return value


class PrintIn(BaseModel):
    printer_id: int
    lot_ids: list[int] = Field(min_length=1, max_length=100)
    copies: int = Field(default=1, ge=1, le=50)
    style: Literal["container", "pack"] = "container"


def _out(printer: LabelPrinter, manager: bool) -> dict:
    out = {"id": printer.id, "name": printer.name, "dpi": printer.dpi, "location_id": printer.location_id, "active": printer.active}
    return {**out, "host": printer.host, "port": printer.port} if manager else out


def _checked(db: Session, user: User, body: PrinterIn, exclude: int | None = None) -> None:
    try:
        private_addresses(body.host, body.port)
    except PrinterError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    if body.location_id is not None:
        check_location(user, db, body.location_id)
    if db.scalar(select(LabelPrinter.id).where(LabelPrinter.name.ilike(body.name), LabelPrinter.id != (exclude or 0))):
        raise HTTPException(status.HTTP_409_CONFLICT, "A printer with that name already exists")


@router.get("")
def list_printers(user: User = Depends(any_of(*USERS)), db: Session = Depends(get_db)):
    manager = "lot.manage" in permissions_of(user)
    stmt = select(LabelPrinter).order_by(LabelPrinter.name)
    if not manager:
        stmt = stmt.where(LabelPrinter.active.is_(True))
    return [_out(p, manager) for p in db.scalars(stmt)]


@router.post("", status_code=201)
def add_printer(body: PrinterIn, user: User = Depends(require("lot.manage")), db: Session = Depends(get_db)):
    _checked(db, user, body)
    printer = LabelPrinter(**body.model_dump())
    db.add(printer)
    db.flush()
    audit(db, user, "label_printer.create", "label_printer", printer.id, None, {"name": printer.name, "host": printer.host, "port": printer.port})
    db.commit()
    return _out(printer, True)


@router.put("/{printer_id}")
def update_printer(printer_id: int, body: PrinterIn, user: User = Depends(require("lot.manage")), db: Session = Depends(get_db)):
    printer = db.get(LabelPrinter, printer_id)
    if not printer:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Printer not found")
    _checked(db, user, body, printer.id)
    before = {"name": printer.name, "host": printer.host, "port": printer.port, "dpi": printer.dpi, "active": printer.active}
    for key, value in body.model_dump().items():
        setattr(printer, key, value)
    audit(db, user, "label_printer.update", "label_printer", printer.id, before, body.model_dump())
    db.commit()
    return _out(printer, True)


@router.delete("/{printer_id}")
def delete_printer(printer_id: int, user: User = Depends(require("lot.manage")), db: Session = Depends(get_db)):
    printer = db.get(LabelPrinter, printer_id)
    if not printer:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Printer not found")
    audit(db, user, "label_printer.delete", "label_printer", printer.id, {"name": printer.name, "host": printer.host}, None)
    db.delete(printer)
    db.commit()
    return {"deleted": printer_id}


def _send(printer: LabelPrinter, pages: list[dict]) -> None:
    try:
        send_zpl(printer.host, printer.port, labels.labels_zpl(pages, printer.dpi))
    except PrinterError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"{printer.name}: {exc}") from None


@router.post("/{printer_id}/test")
def test_print(printer_id: int, user: User = Depends(require("lot.manage")), db: Session = Depends(get_db)):
    """One sample label, to check the printer, its address and the label size."""
    printer = db.get(LabelPrinter, printer_id)
    if not printer:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Printer not found")
    _send(printer, [{"code": "TEST-0001", "item": "Test label - chicken breast, skinless", "detail": "24 x 200 g portions, vacuum", "condition": "Vacuum packed, chilled",
                     "supplier": "Sample supplier", "supplier_lot": "L-12345", "produced": "01 Jan 2026", "expiry": "15 Jan 2026", "stamp_label": "Portioned",
                     "stamped": "02 Jan 2026 09:00", "by": "AB", "use_by": "06 Jan 2026 09:00"}])
    audit(db, user, "label_printer.test", "label_printer", printer.id, None, None)
    db.commit()
    return {"printed": 1}


@router.post("/print")
def print_labels(body: PrintIn, user: User = Depends(any_of(*USERS)), db: Session = Depends(get_db)):
    """Sends the labels for some lots straight to a network printer."""
    printer = db.get(LabelPrinter, body.printer_id)
    if not printer or not printer.active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Printer not found")
    pages = label_pages(db, user, body.lot_ids, body.copies, body.style)
    _send(printer, pages)
    audit(db, user, "label.print", "label_printer", printer.id, None, {"lots": body.lot_ids, "copies": body.copies, "style": body.style})
    db.commit()
    return {"printed": len(pages), "printer": printer.name}
