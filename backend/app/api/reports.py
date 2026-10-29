from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import timeutil
from ..audit import audit
from ..db import get_db
from ..deps import check_location, require, scoped_locations
from ..models import Employee, User
from ..services import exporters
from ..services.organization import report_identity, stamp
from ..services.records import KINDS, MOVEMENTS, Filters, build_record
from ..services.reports import PERIODS, REPORTS, build_report

PREVIEW_ROWS = 200
MAX_PDF_ROWS = 4000

router = APIRouter(prefix="/api/reports", tags=["reports"])

MEDIA = {"csv": "text/csv", "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
         "pdf": "application/pdf"}
RENDER = {"csv": exporters.to_csv, "xlsx": exporters.to_xlsx, "pdf": exporters.to_pdf}
RECORD_RENDER = {"csv": exporters.record_to_csv, "xlsx": exporters.record_to_xlsx, "pdf": exporters.record_to_pdf}


def _build(db: Session, user: User, period: str, anchor: date | None, location_id: int | None,
           employee_id: int | None) -> dict:
    if period not in PERIODS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown report period")
    if location_id is not None:
        check_location(user, db, location_id)
    try:
        report = build_report(db, timeutil.utc_now(), scoped_locations(user, db), period, anchor, location_id, employee_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    name, position = _author(db, user)
    return {**report, "prepared_by": name, "prepared_position": position, "organization": report_identity(db)}


def _author(db: Session, user: User) -> tuple[str, str]:
    """The person exporting the report: their name and, separately, their job title."""
    emp = db.scalar(select(Employee).where(Employee.user_id == user.id))
    return (emp.full_name, emp.job_title) if emp else (user.email, user.role.name.replace("_", " ").capitalize())


def _record(db: Session, user: User, kind: str, date_from: date | None, date_to: date | None, f: Filters) -> dict:
    if kind not in KINDS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown record type")
    if f.location_id is not None:
        check_location(user, db, f.location_id)
    if f.movement and f.movement not in MOVEMENTS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown movement type")
    if f.frequency and f.frequency not in ("daily", "weekly"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown checklist frequency")
    now = timeutil.utc_now()
    day_to = date_to or now.date()
    day_from = date_from or day_to
    name, position = _author(db, user)
    try:
        doc = build_record(db, now, scoped_locations(user, db), kind, day_from, day_to, f, name)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    identity = report_identity(db)
    return {**doc, "prepared_position": position, "generated_at": stamp(now, identity["timezone"]), "organization": identity}


@router.get("/records/{kind}")
def record(kind: str, date_from: date | None = None, date_to: date | None = None, location_id: int | None = None,
           equipment_id: int | None = None, employee_id: int | None = None, supplier_id: int | None = None,
           item_id: int | None = None, movement: str | None = None, frequency: str | None = None, status: str | None = None,
           food_group: str | None = None, equipment_kind: str | None = None, template_id: int | None = None,
           user: User = Depends(require("report.view")), db: Session = Depends(get_db)):
    f = Filters(location_id, equipment_id, employee_id, supplier_id, item_id, movement, frequency, status, food_group, equipment_kind, template_id)
    doc = _record(db, user, kind, date_from, date_to, f)
    return {**doc, "groups": [{**g, "row_count": len(g["rows"]), "rows": g["rows"][:PREVIEW_ROWS]} for g in doc["groups"]]}


@router.get("/records/{kind}/export")
def export_record(kind: str, fmt: Literal["csv", "xlsx", "pdf"] = "pdf", date_from: date | None = None,
                  date_to: date | None = None, location_id: int | None = None, equipment_id: int | None = None,
                  employee_id: int | None = None, supplier_id: int | None = None, item_id: int | None = None,
                  movement: str | None = None, frequency: str | None = None, status: str | None = None, food_group: str | None = None,
                  equipment_kind: str | None = None, template_id: int | None = None,
                  user: User = Depends(require("report.export")), db: Session = Depends(get_db)):
    f = Filters(location_id, equipment_id, employee_id, supplier_id, item_id, movement, frequency, status, food_group, equipment_kind, template_id)
    doc = _record(db, user, kind, date_from, date_to, f)
    rows = sum(len(g["rows"]) for g in doc["groups"])
    if fmt == "pdf" and rows > MAX_PDF_ROWS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"This record has {rows:,} rows, more than a PDF can hold ({MAX_PDF_ROWS:,}). Choose a shorter period, one location or one employee, or download Excel or CSV.")
    audit(db, user, "report.export", "record", None, None, {"kind": kind, "format": fmt, "from": doc["period"]["from"],
                                                           "to": doc["period"]["to"], "location_id": location_id})
    db.commit()
    filename = f"{kind}-record-{doc['period']['from']}-to-{doc['period']['to']}.{fmt}"
    return Response(RECORD_RENDER[fmt](doc), media_type=MEDIA[fmt], headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("")
def catalog(user: User = Depends(require("report.view"))):
    return {p: [fn.__name__.removeprefix("sec_") for fn in REPORTS[p]] for p in PERIODS}


@router.get("/{period}")
def report(period: str, anchor: date | None = None, location_id: int | None = None, employee_id: int | None = None,
           user: User = Depends(require("report.view")), db: Session = Depends(get_db)):
    return _build(db, user, period, anchor, location_id, employee_id)


@router.get("/{period}/export")
def export(period: str, fmt: Literal["csv", "xlsx", "pdf"] = "xlsx", anchor: date | None = None,
           location_id: int | None = None, employee_id: int | None = None,
           user: User = Depends(require("report.export")), db: Session = Depends(get_db)):
    data = _build(db, user, period, anchor, location_id, employee_id)
    audit(db, user, "report.export", "report", None, None, {"period": period, "format": fmt, "from": data["period"]["from"],
                                                           "to": data["period"]["to"], "location_id": location_id})
    db.commit()
    filename = f"stewarding-{period}-{data['period']['from']}.{fmt}"
    return Response(RENDER[fmt](data), media_type=MEDIA[fmt],
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})
