"""Printable record documents: one titled table per location and monitoring point or checklist, for audits and month end."""
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from .. import timeutil
from ..models import (ChecklistInstance, ChecklistTask, ChecklistTemplate, CorrectiveAction, Employee, Equipment,
                      EquipmentSchedule, FoodItem, InventoryCategory, InventoryItem, Location, Lot, Receipt, ReceiptLine, StockTransaction,
                      Supplier, TemperatureReading)
from . import metrics
from .traceability import CONDITIONS, GROUPS
from .costing import MEASURES, category_rows, cost_report
from .monitoring import describe
from .reference import user_names
from .settings import get_setting

KINDS = {"monitoring": "Monitoring Record", "checklists": "Checklist Record", "checklist_chart": "Checklist Completion Chart",
         "attendance": "Attendance Record", "attendance_sheet": "Employee Attendance Sheet", "receipts": "Receipts and Invoices", "movements": "Stock Issues and Movements",
         "stock_cost": "Stock Cost Report", "stock_cost_category": "Stock Cost by Category", "inventory_detail": "Detailed Inventory Report", "lots": "Lot Register"}
STATUS_FILTERS = {"monitoring": ("passed", "failed", "awaiting"),
                  "checklists": ("pending", "completed", "pending_verification", "verified", "failed", "waived"),
                  "attendance": ("present", "late", "absent", "leave", "week_off"),
                  "lots": ("active", "used_up", "discarded", "on_hold")}
MAX_DAYS = 731
CHART_DAYS = 31
MOVEMENTS = {"receipts": ("receipt",), "issues": ("issue",), "returns": ("return",), "transfers": ("transfer_in", "transfer_out"),
             "breakage": ("damage", "breakage"), "adjustments": ("adjustment",), "opening": ("opening",)}


@dataclass
class Filters:
    location_id: int | None = None
    equipment_id: int | None = None
    employee_id: int | None = None
    supplier_id: int | None = None
    item_id: int | None = None
    movement: str | None = None
    frequency: str | None = None
    status: str | None = None
    food_group: str | None = None
    equipment_kind: str | None = None
    template_id: int | None = None


def _local(dt: datetime | None, tz: str) -> str:
    return timeutil.to_local(dt, tz).strftime("%d %b %Y %H:%M") if dt else ""


def _limits(reading: TemperatureReading) -> str:
    if reading.value_type == "yes_no":
        return "Must be Yes"
    if reading.value_type in ("text", "choice", "date", "time", "signature", "image"):
        return {"choice": "Choice", "date": "Date", "time": "Time", "signature": "Signature", "image": "Image"}.get(reading.value_type, "Written answer")
    low = "-" if reading.min_limit is None else f"{reading.min_limit.normalize():f}"
    high = "-" if reading.max_limit is None else f"{reading.max_limit.normalize():f}"
    return f"{low} to {high} {reading.unit or ''}".strip()


def _bounds(day_from: date, day_to: date, tz: str) -> tuple[datetime, datetime]:
    return (timeutil.local_to_utc(day_from, time(0, 0), tz), timeutil.local_to_utc(day_to + timedelta(days=1), time(0, 0), tz))


def _names(db: Session) -> dict[int, str]:
    return user_names(db)


def _locations(db: Session, scope: set[int] | None, location_id: int | None) -> list[Location]:
    stmt = select(Location).where(Location.active.is_(True))
    if location_id is not None:
        stmt = stmt.where(Location.id == location_id)
    elif scope is not None:
        stmt = stmt.where(Location.id.in_(scope))
    return list(db.scalars(stmt.order_by(Location.name)))


READING_STATUS = {"passed": lambda r: r.passed, "failed": lambda r: not r.passed, "awaiting": lambda r: not r.reviewed_at and not r.rejected_at}


def _monitoring_groups(db: Session, locations: list[Location], day_from: date, day_to: date, equipment_id: int | None,
                       status: str | None = None, kind: str | None = None) -> list[dict]:
    """One table per monitoring point, including points with nothing recorded in the period."""
    names = _names(db)
    groups = []
    for loc in locations:
        start, end = _bounds(day_from, day_to, loc.timezone)
        stmt = select(Equipment).where(Equipment.location_id == loc.id)
        if equipment_id is not None:
            stmt = stmt.where(Equipment.id == equipment_id)
        if kind:
            stmt = stmt.where(Equipment.kind == kind)
        for eq in db.scalars(stmt.order_by(Equipment.code)):
            readings = list(db.scalars(select(TemperatureReading).where(
                TemperatureReading.equipment_id == eq.id, TemperatureReading.recorded_at >= start,
                TemperatureReading.recorded_at < end).order_by(TemperatureReading.recorded_at)))
            if status:
                readings = [r for r in readings if READING_STATUS[status](r)]
            if not readings and (status or not eq.active):
                continue
            actions = {a.reading_id: a for a in db.scalars(select(CorrectiveAction).where(
                CorrectiveAction.reading_id.in_([r.id for r in readings])))}
            lead = db.scalar(select(func.min(EquipmentSchedule.id)).where(EquipmentSchedule.equipment_id == eq.id, EquipmentSchedule.phase == "start"))
            time_out = dict(db.execute(select(TemperatureReading.start_reading_id, func.min(TemperatureReading.recorded_at)).where(
                TemperatureReading.start_reading_id.in_([r.id for r in readings if r.schedule_id == lead]))
                .group_by(TemperatureReading.start_reading_id)).all()) if lead else {}
            rows = []
            for r in readings:
                a = actions.get(r.id)
                taken = f"{a.action} ({names.get(a.taken_by, '')}, {a.status.replace('_', ' ')})" if a and a.action else (
                    a.status.replace("_", " ") if a else "")
                when = _local(r.recorded_at, loc.timezone)
                out = (_local(time_out[r.id], loc.timezone) if r.id in time_out else "Pending") if r.schedule_id == lead else ""
                rows.append({
                    "date": when[:11], "time": when[12:], "time_out": out, "check": r.stage[:1].upper() + r.stage[1:].replace("_", " "), "measure": r.parameter,
                    "value": describe(r), "limits": _limits(r),
                    "result": "Pass" if r.passed else "FAIL", "reference": r.reference or "",
                    "recorded_by": names.get(r.recorded_by, ""),
                    "approved_by": f"Rejected by {names.get(r.rejected_by, '')}: {r.reject_reason}" if r.rejected_at
                    else f"{names.get(r.reviewed_by, '')} {_local(r.reviewed_at, loc.timezone)}".strip() if r.reviewed_at else "Awaiting approval",
                    "corrective_action": taken})
            failed = sum(1 for r in readings if not r.passed)
            columns = [("date", "Date"), ("time", "Time in" if lead else "Time")] + ([("time_out", "Time out")] if lead else []) + [
                ("check", "Check"), ("measure", "Measure"), ("value", "Value"), ("limits", "Limits"), ("result", "Result"),
                ("reference", "Item / batch"), ("recorded_by", "Recorded by"), ("approved_by", "Approved by"),
                ("corrective_action", "Corrective action")]
            groups.append({
                "title": f"{loc.name} - {eq.name} ({eq.code})",
                "meta": [("Location", loc.name), ("Monitoring point", f"{eq.name} ({eq.code})"), ("Type", eq.kind)],
                "columns": columns, "rows": rows,
                "totals": [("Checks recorded", len(readings)), ("Passed", len(readings) - failed), ("Failed", failed),
                           ("Awaiting approval", sum(1 for r in readings if not r.reviewed_at and not r.rejected_at))]
                + ([("Waiting for time out", sum(1 for r in readings if r.schedule_id == lead and r.id not in time_out))] if lead else [])})
    return groups


def _stock_cost_groups(db: Session, locations: list[Location], day_from: date, day_to: date) -> list[dict]:
    """Per location and item: opening value, purchases, closing value and the cost consumed, at weighted average cost."""
    groups = []
    for loc in locations:
        start, end = _bounds(day_from, day_to, loc.timezone)
        report = cost_report(db, loc.id, start, end)
        if not report["rows"]:
            continue
        rows = [{"category": r["category"], "item": f"{r['code']} - {r['name']}", "average_cost": "" if r["average_cost"] is None else f"{r['average_cost']:.4f}",
                 "opening_value": f"{r['opening_value']:.3f}", "purchases": f"{r['purchases']:.3f}",
                 "net_transfers_returns": f"{r['returns'] + r['transfers_in'] - r['transfers_out']:.3f}",
                 "closing_value": f"{r['closing_value']:.3f}", "cost_consumed": f"{r['cost_consumed']:.3f}", "issued": f"{r['issued']:.3f}",
                 "breakage_damage": f"{r['breakage_damage']:.3f}", "count_adjustments": f"{r['count_adjustments']:.3f}"}
                for r in sorted(report["rows"], key=lambda r: (r["category"], r["code"]))]
        t = report["totals"]
        groups.append({
            "title": f"{loc.name} - Stock cost", "meta": [("Location", loc.name), ("Costing method", "Weighted average cost"), ("Purchases counted on", "Invoice date")],
            "columns": [("category", "Category"), ("item", "Item"), ("average_cost", "Average cost"), ("opening_value", "Opening value"), ("purchases", "Purchases"),
                        ("net_transfers_returns", "Returns and transfers (net)"), ("closing_value", "Closing value"),
                        ("cost_consumed", "Cost consumed"), ("issued", "of which issued"), ("breakage_damage", "of which breakage and damage"),
                        ("count_adjustments", "Count gain (+) or loss (-)")],
            "rows": rows,
            "totals": [("Opening value", f"{t['opening_value']:.3f}"), ("Purchases", f"{t['purchases']:.3f}"), ("Closing value", f"{t['closing_value']:.3f}"),
                       ("Cost consumed", f"{t['cost_consumed']:.3f}"), ("Issued", f"{t['issued']:.3f}"), ("Breakage and damage", f"{t['breakage_damage']:.3f}"),
                       ("Count gain (+) or loss (-)", f"{t['count_adjustments']:.3f}")]})
    return groups


def _stock_cost_category_groups(db: Session, locations: list[Location], day_from: date, day_to: date) -> list[dict]:
    """The cost report one line per category, per location and for all locations together."""
    columns = [("category", "Category"), ("items", "Items"), ("opening_value", "Opening value"), ("purchases", "Purchases"),
               ("closing_value", "Closing value"), ("cost_consumed", "Cost consumed"), ("share", "Share of cost"), ("issued", "of which issued"),
               ("breakage_damage", "of which breakage and damage"), ("count_adjustments", "Count gain (+) or loss (-)")]
    groups, all_totals = [], []
    together: dict[str, dict] = defaultdict(lambda: defaultdict(Decimal))
    for loc in locations:
        start, end = _bounds(day_from, day_to, loc.timezone)
        report = cost_report(db, loc.id, start, end)
        if not report["rows"]:
            continue
        for line in report["by_category"]:
            together[line["category"]]["items"] += line["items"]
            for key in MEASURES:
                together[line["category"]][key] += Decimal(str(line[key]))
        all_totals.append(report["totals"])
        groups.append(_category_group(f"{loc.name} - Stock cost by category", [("Location", loc.name), ("Costing method", "Weighted average cost"), ("Purchases counted on", "Invoice date")],
                                      columns, report["by_category"], report["totals"]))
    if len(groups) > 1:
        grand = {k: sum(Decimal(str(t[k])) for t in all_totals) for k in MEASURES}
        groups.append(_category_group("All locations - Stock cost by category",
                                      [("Locations", ", ".join(loc.name for loc in locations)), ("Costing method", "Weighted average cost"), ("Purchases counted on", "Invoice date")],
                                      columns, category_rows(together, grand["cost_consumed"]), {k: float(v) for k, v in grand.items()}))
    return groups


QTY_PARTS = ("opening_qty", "purchases_qty", "returns_qty", "transfers_in_qty", "transfers_out_qty", "issued_qty", "breakage_damage_qty", "missing_written_off_qty",
             "baseline_adjustments_qty", "count_adjustments_qty", "closing_qty")
VALUE_PARTS = ("opening_value", "purchases", "returns", "transfers_in", "transfers_out", "issued", "breakage_damage", "missing_written_off", "baseline_adjustments",
               "count_adjustments", "closing_value")


def _item_columns(with_split: bool = False) -> list[tuple[str, str]]:
    cols = [("category", "Category"), ("item", "Item"), ("average_cost", "Average cost"), ("opening_qty", "Opening qty"), ("purchases_qty", "Bought"),
            ("returns_qty", "Returns (net)"), ("transfers_in_qty", "Transfers in"), ("transfers_out_qty", "Transfers out"), ("issued_qty", "Issued"),
            ("breakage_damage_qty", "Breakage"), ("missing_written_off_qty", "Written off"), ("baseline_adjustments_qty", "Baseline"),
            ("count_adjustments_qty", "Count +/-"), ("closing_qty", "Closing qty"), ("closing_value", "Closing value")]
    return cols + ([("split", "Held at")] if with_split else [])


def _category_columns() -> list[tuple[str, str]]:
    return [("category", "Category"), ("items", "No."), ("opening_qty", "Opening qty"), ("opening_value", "Opening value"), ("purchases", "Purchases"), ("returns", "Returns (net)"),
            ("transfers_in", "Transfers in"), ("transfers_out", "Transfers out"), ("issued", "Issued"), ("breakage_damage", "Breakage and damage"),
            ("missing_written_off", "Missing or written off"), ("baseline_adjustments", "Baseline"), ("count_adjustments", "Count gain (+) or loss (-)"),
            ("closing_qty", "Closing qty"), ("closing_value", "Closing value")]


COMPARE_VALUES = (("opening_value", "Opening value"), ("purchases", "Purchases"), ("returns", "Returns (net)"), ("transfers_in", "Transfers in"),
                  ("transfers_out", "Transfers out"), ("issued", "Issued"), ("breakage_damage", "Breakage and damage"), ("missing_written_off", "Missing or written off"),
                  ("baseline_adjustments", "Baseline"), ("count_adjustments", "Count gain (+) or loss (-)"), ("closing_value", "Closing value"), ("cost_consumed", "Cost consumed"))


def _compare_group(title: str, meta: list, period: dict, year: dict, qty: tuple[int, int, int, int]) -> dict:
    """This period beside the year so far: the same lines, one column each."""
    rows = [{"measure": label, "period": f"{period[key]:.3f}", "ytd": f"{year[key]:.3f}"} for key, label in COMPARE_VALUES]
    rows[0:0] = [{"measure": "Opening qty", "period": qty[0], "ytd": qty[1]}]
    rows.append({"measure": "Closing qty", "period": qty[2], "ytd": qty[3]})
    return {"title": title, "meta": meta, "columns": [("measure", "Measure"), ("period", "This period"), ("ytd", "Year to date")], "rows": rows, "totals": []}


def _inventory_detail_groups(db: Session, locations: list[Location], day_from: date, day_to: date) -> list[dict]:
    """Location by location and item by item: opening, what came in and went out of each kind, and closing, in units and in money."""
    meta_common = [("Costing method", "Weighted average cost"), ("Purchases counted on", "Invoice date"), ("Breakage counted on", "Day reported"),
                   ("Reading the columns", "Breakage includes damage; Written off includes missing stock; Count +/- is the gain (+) or loss (-) found by counts; "
                                           "Baseline is a first count round's accepted gap; Returns are net of supplier returns")]
    per_location, rows_by_item = [], defaultdict(list)
    for loc in locations:
        start, end = _bounds(day_from, day_to, loc.timezone)
        report = cost_report(db, loc.id, start, end)
        rows = sorted(report["rows"], key=lambda r: (r["category"], r["code"]))
        if rows:
            per_location.append((loc, rows))
        for r in rows:
            rows_by_item[r["item_id"]].append((loc.name, r))

    def category_block(title: str, meta: list, rows: list[dict]) -> dict:
        sums: dict[str, dict] = {}
        for r in rows:
            s = sums.setdefault(r["category"], {"items": 0, **{k: 0 for k in (*QTY_PARTS, *VALUE_PARTS)}})
            s["items"] += 1
            for k in (*QTY_PARTS, *VALUE_PARTS):
                s[k] += r[k]
        lines = [{"category": name, "items": s["items"], **{k: (f"{s[k]:.3f}" if k in VALUE_PARTS else s[k]) for k in (*QTY_PARTS, *VALUE_PARTS)}} for name, s in sorted(sums.items())]
        total = {k: sum(s[k] for s in sums.values()) for k in (*QTY_PARTS, *VALUE_PARTS)}
        return {"title": title, "meta": meta, "columns": _category_columns(), "rows": lines,
                "totals": [("Opening value", f"{total['opening_value']:.3f}"), ("Purchases", f"{total['purchases']:.3f}"), ("Closing value", f"{total['closing_value']:.3f}"),
                           ("Closing qty", total["closing_qty"])]}

    def item_row(r: dict, split: str | None = None) -> dict:
        row = {"category": r["category"], "item": f"{r['code']} - {r['name']}", "average_cost": "" if r["average_cost"] is None else f"{r['average_cost']:.4f}",
               **{k: r[k] for k in QTY_PARTS}, "closing_value": f"{r['closing_value']:.3f}"}
        return {**row, "split": split} if split is not None else row

    groups = []
    everything = [r for _, rows in per_location for r in rows]
    year_start = date(day_to.year, 1, 1)
    compare: dict[int, dict] = {}
    if day_from > year_start:  # a period shorter than the year so far: show the year to date beside it
        for loc, rows in per_location:
            start, end = _bounds(year_start, day_to, loc.timezone)
            year = cost_report(db, loc.id, start, end)
            period = cost_report(db, loc.id, *_bounds(day_from, day_to, loc.timezone))
            compare[loc.id] = {"period": period["totals"], "year": year["totals"],
                               "qty": (sum(r["opening_qty"] for r in rows), sum(r["opening_qty"] for r in year["rows"]),
                                       sum(r["closing_qty"] for r in rows), sum(r["closing_qty"] for r in year["rows"]))}
        ytd_label = f"1 Jan to {day_to.strftime('%d %b %Y')}"
        if compare:
            total = lambda which: {k: sum(c[which][k] for c in compare.values()) for k in MEASURES}  # noqa: E731
            qty = tuple(sum(c["qty"][i] for c in compare.values()) for i in range(4))
            if len(per_location) != 1:
                groups.append(_compare_group("All locations - This period and year to date", [("Locations", ", ".join(loc.name for loc, _ in per_location)),
                                                                                           ("Year to date", ytd_label), *meta_common], total("period"), total("year"), qty))
    if len(per_location) != 1:  # one location: its own block below is the whole picture
        groups.append(category_block("All locations - Cost by category", [("Locations", ", ".join(loc.name for loc in locations)), *meta_common], everything))
    for loc, rows in per_location:
        if loc.id in compare:
            groups.append(_compare_group(f"{loc.name} - This period and year to date", [("Location", loc.name), ("Year to date", ytd_label), *meta_common],
                                         compare[loc.id]["period"], compare[loc.id]["year"], compare[loc.id]["qty"]))
        groups.append(category_block(f"{loc.name} - Cost by category", [("Location", loc.name), *meta_common], rows))
        groups.append({"title": f"{loc.name} - Stock by item", "meta": [("Location", loc.name), *meta_common], "columns": _item_columns(), "rows": [item_row(r) for r in rows],
                       "totals": [("Items", len(rows)), ("Opening qty", sum(r["opening_qty"] for r in rows)), ("Closing qty", sum(r["closing_qty"] for r in rows)),
                                  ("Closing value", f"{sum(r['closing_value'] for r in rows):.3f}")]})
    if len(per_location) > 1:
        totals_rows = []
        for item_id, parts in sorted(rows_by_item.items(), key=lambda kv: (kv[1][0][1]["category"], kv[1][0][1]["code"])):
            first = parts[0][1]
            merged = {**first, **{k: sum(p[1][k] for p in parts) for k in (*QTY_PARTS, "closing_value")}}
            held = ", ".join(f"{name} {r['closing_qty']}" for name, r in parts if r["closing_qty"])
            merged["average_cost"] = (merged["closing_value"] / merged["closing_qty"]) if merged["closing_qty"] else first["average_cost"]
            totals_rows.append(item_row(merged, held))
        groups.append({"title": "All locations - Total per item", "meta": [("Locations", ", ".join(loc.name for loc, _ in per_location)), *meta_common],
                       "columns": _item_columns(with_split=True), "rows": totals_rows,
                       "totals": [("Items", len(totals_rows)), ("Opening qty", sum(r["opening_qty"] for r in totals_rows)), ("Closing qty", sum(r["closing_qty"] for r in totals_rows)),
                                  ("Closing value", f"{sum(float(r['closing_value']) for r in totals_rows):.3f}")]})
    return groups


def _category_group(title: str, meta: list, columns: list, lines: list[dict], totals: dict) -> dict:
    rows = [{**line, **{k: f"{line[k]:.3f}" for k in MEASURES}, "share": f"{line['share']:.1f}%"} for line in lines]
    return {"title": title, "meta": meta, "columns": columns, "rows": rows,
            "totals": [("Opening value", f"{totals['opening_value']:.3f}"), ("Purchases", f"{totals['purchases']:.3f}"), ("Closing value", f"{totals['closing_value']:.3f}"),
                       ("Cost consumed", f"{totals['cost_consumed']:.3f}"), ("Breakage and damage", f"{totals['breakage_damage']:.3f}"),
                       ("Count gain (+) or loss (-)", f"{totals['count_adjustments']:.3f}")]}


def _checklist_groups(db: Session, locations: list[Location], day_from: date, day_to: date,
                      frequency: str | None = None, employee_id: int | None = None, status: str | None = None,
                      template_id: int | None = None) -> list[dict]:
    names = _names(db)
    groups = []
    for loc in locations:
        rows_by_template: dict[str, list] = {}
        stmt = (select(ChecklistInstance, ChecklistTask, ChecklistTemplate)
                .join(ChecklistTask, ChecklistTask.id == ChecklistInstance.task_id)
                .join(ChecklistTemplate, ChecklistTemplate.id == ChecklistTask.template_id)
                .where(ChecklistInstance.location_id == loc.id, ChecklistInstance.local_date >= day_from,
                       ChecklistInstance.local_date <= day_to)
                .order_by(ChecklistInstance.local_date, ChecklistTemplate.name, ChecklistTask.id))
        if frequency:
            stmt = stmt.where(ChecklistTemplate.frequency == frequency)
        if status:
            stmt = stmt.where(ChecklistInstance.status == status)
        if template_id is not None:
            stmt = stmt.where(ChecklistTemplate.id == template_id)
        if employee_id is not None:
            emp_user = db.scalar(select(Employee.user_id).where(Employee.id == employee_id))
            stmt = stmt.where((ChecklistInstance.assigned_employee_id == employee_id) | (ChecklistInstance.completed_by == (emp_user or -1)))
        for inst, task, template in db.execute(stmt):
            rows_by_template.setdefault(f"{template.name} ({template.frequency})", []).append({
                "date": inst.local_date.strftime("%d %b %Y"), "task": task.description, "status": inst.status.replace("_", " "),
                "completed_by": names.get(inst.completed_by, ""), "completed_at": _local(inst.completed_at, loc.timezone),
                "reading": "" if inst.reading is None else f"{inst.reading.normalize():f}",
                "comment": inst.comment or inst.waive_reason or "",
                "verified_by": names.get(inst.verified_by, ""), "verified_at": _local(inst.verified_at, loc.timezone)})
        for title, rows in rows_by_template.items():
            counts = {s: sum(1 for r in rows if r["status"] == s) for s in ("verified", "pending verification", "completed", "failed")}
            columns = [("date", "Date"), ("task", "Task"), ("status", "Status"), ("completed_by", "Completed by"),
                       ("completed_at", "Completed at"), ("reading", "Reading"), ("comment", "Comment"),
                       ("verified_by", "Approved by"), ("verified_at", "Approved at")]
            if not any(r["reading"] for r in rows):
                columns = [c for c in columns if c[0] != "reading"]  # only tasks that ask for a measurement have one
            groups.append({
                "title": f"{loc.name} - {title}",
                "meta": [("Location", loc.name), ("Checklist", title)],
                "columns": columns,
                "rows": rows,
                "totals": [("Tasks", len(rows)), ("Approved", counts["verified"]), ("Awaiting approval", counts["pending verification"]),
                           ("Rejected", counts["failed"])]})
    return groups


def _initials(name: str | None, legend: dict[str, str]) -> str:
    if not name:
        return ""
    base = "".join(part[0] for part in name.split()[:2]).upper() or "?"
    code, n = base, 2
    while legend.get(code, name) != name:
        code, n = f"{base}{n}", n + 1
    legend[code] = name
    return code


CHART_KEY = "Key: tick = done and approved, amber dotted tick = done, awaiting approval, cross = not done or rejected, W = waived, - = not due"


def _chart_groups(db: Session, now: datetime, scope, f: Filters, day_from: date, day_to: date) -> list[dict]:
    if (day_to - day_from).days >= CHART_DAYS:
        raise ValueError(f"The completion chart covers at most {CHART_DAYS} days; use the checklist record for longer periods")
    names = _names(db)
    days = list(metrics.daterange(day_from, day_to))
    groups = []
    for win in metrics.windows(db, now, scope, f.location_id, day_from, day_to):
        stats = metrics.checklist_stats(db, win, now, f.employee_id, f.frequency)
        by_template: dict[str, dict[tuple[int, str], dict]] = {}
        exceptions: list[dict] = []
        for inst, task, tpl, state in stats["rows"]:
            if f.template_id is not None and tpl.id != f.template_id:
                continue
            title = f"{tpl.name} ({tpl.frequency})"
            row = by_template.setdefault(title, {}).setdefault((task.id, task.description), {})
            row.setdefault(inst.local_date, []).append((inst, state))
            if state in ("failed", "overdue", "waived"):
                exceptions.append({"date": inst.local_date.strftime("%d %b %Y"), "task": task.description,
                                   "status": {"failed": "Rejected", "overdue": "Not done", "waived": "Waived"}[state],
                                   "completed_by": names.get(inst.completed_by, ""), "approved_by": names.get(inst.verified_by, ""),
                                   "reason": inst.comment or inst.waive_reason or ""})
        for title, tasks in by_template.items():
            legend: dict[str, str] = {}
            rows, done, expected = [], 0, 0
            for (_, description), by_day in tasks.items():
                row = {"task": description}
                for i, day in enumerate(days):
                    items = by_day.get(day)
                    if not items:
                        row[f"d{i}"] = {"s": "na"}
                        continue
                    states = {state for _, state in items}
                    symbol = ("fail" if states & {"failed", "overdue"} else "pending" if "pending_verification" in states
                              else "waived" if states == {"waived"} else "ok" if states & {"verified", "completed"} else "na")
                    first = next((inst for inst, _ in items if inst.completed_by), items[0][0])
                    row[f"d{i}"] = {"s": symbol, "by": _initials(names.get(first.completed_by), legend),
                                    "ver": _initials(names.get(first.verified_by), legend)}
                    if symbol != "na" and symbol != "waived":
                        expected += 1
                        done += symbol in ("ok", "pending")
                rows.append(row)
            groups.append({
                "title": f"{win.loc.name} - {title}", "layout": "chart",
                "meta": [("Location", win.loc.name), ("Checklist", title), ("Columns", "Each column is a date: weekday and day of the month"), ("Initials", ", ".join(f"{k} = {v}" for k, v in sorted(legend.items())) or "-")],
                "legend": CHART_KEY,
                "columns": [("task", "Task")] + [(f"d{i}", f"{day.strftime('%a')}\n{day.day}") for i, day in enumerate(days)],
                "rows": rows,
                "totals": [("Tasks", len(rows)), ("Completed", f"{done}/{expected}" if expected else "0/0"),
                           ("Compliance", f"{metrics.pct(done, expected)}%" if expected else "n/a")]})
        if exceptions:
            groups.append({
                "title": f"{win.loc.name} - Exceptions and follow-up", "meta": [("Location", win.loc.name)],
                "columns": [("date", "Date"), ("task", "Task"), ("status", "Status"), ("completed_by", "Completed by"),
                            ("approved_by", "Approved by"), ("reason", "Reason or comment")],
                "rows": exceptions, "totals": [("Exceptions", len(exceptions))]})
    return groups


PRESENT_STATUSES = ("present", "late", "on_duty", "missed_checkout", "unscheduled")
LEAVE_DAY_STATUSES = ("sick_leave", "annual_leave", "unpaid_leave", "other_leave")
ATTENDANCE_STATUS = {"present": lambda r: r["status"] in PRESENT_STATUSES, "late": lambda r: r["status"] == "late" or (r["late_minutes"] or 0) > 0,
                     "absent": lambda r: r["status"] == "absent", "leave": lambda r: r["status"] in LEAVE_DAY_STATUSES,
                     "week_off": lambda r: r["status"] == "week_off"}


def _attendance_groups(db: Session, now: datetime, scope, f: Filters, day_from: date, day_to: date) -> list[dict]:
    groups = []
    for win in metrics.windows(db, now, scope, f.location_id, day_from, day_to):
        stats = metrics.attendance_stats(db, win, now, f.employee_id)
        shown = [r for r in stats["rows"] if ATTENDANCE_STATUS[f.status](r)] if f.status else stats["rows"]
        if not shown:
            continue
        tz = win.loc.timezone
        rows = [{"date": r["day"].strftime("%d %b %Y"), "employee": r["name"], "shift": r["shift"] or "",
                 "status": r["status"].replace("_", " ").capitalize(),
                 "check_in": timeutil.to_local(r["check_in"], tz).strftime("%H:%M") if r["check_in"] else "",
                 "check_out": timeutil.to_local(r["check_out"], tz).strftime("%H:%M") if r["check_out"] else "",
                 "late": r["late_minutes"] or "", "worked": _hm(r["payable_minutes"]), "overtime": _hm(r["overtime_minutes"]),
                 "note": r["note"] or "", "location_check": "; ".join(dict.fromkeys(r["geo_flags"]))} for r in shown]
        groups.append({
            "title": f"{win.loc.name} - Attendance", "meta": [("Location", win.loc.name)],
            "columns": [("date", "Date"), ("employee", "Employee"), ("shift", "Shift"), ("status", "Status"), ("check_in", "In"),
                        ("check_out", "Out"), ("late", "Late (min)"), ("worked", "Worked"), ("overtime", "Overtime"), ("note", "Note"),
                        ("location_check", "Location check")],
            "rows": rows,
            "totals": [("Scheduled", stats["scheduled"]), ("Present", sum(1 for r in stats["rows"] if r["status"] in PRESENT_STATUSES)), ("Late", stats["late"]),
                       ("Absent", stats["absent"]), ("On leave", stats["on_leave"]), ("Week off", stats["week_off"])]})
    if len(groups) > 1 and not get_setting(db, "attendance.by_location"):
        totals: dict[str, int] = {}
        for g in groups:
            for label, n in g["totals"]:
                totals[label] = totals.get(label, 0) + n
        return [{"title": "Attendance", "meta": [], "columns": groups[0]["columns"], "rows": [r for g in groups for r in g["rows"]], "totals": list(totals.items())}]
    if groups and not get_setting(db, "attendance.by_location"):
        groups[0]["title"], groups[0]["meta"] = "Attendance", []
    return groups


LEAVE_STATUSES = ("sick_leave", "annual_leave", "unpaid_leave", "other_leave")


def _attendance_sheet_groups(db: Session, now: datetime, scope, f: Filters, day_from: date, day_to: date) -> list[dict]:
    """One page per employee: day totals first, then every scheduled, worked or recorded day."""
    people = {e.id: e for e in db.scalars(select(Employee))}
    sheets: dict[int, dict] = {}
    for win in metrics.windows(db, now, scope, f.location_id, day_from, day_to):
        tz = win.loc.timezone
        for r in metrics.attendance_stats(db, win, now, f.employee_id)["rows"]:
            sheet = sheets.setdefault(r["employee_id"], {"places": set(), "rows": []})
            sheet["places"].add(win.loc.name)
            sheet["rows"].append((r["day"], {
                "date": r["day"].strftime("%d %b %Y"), "weekday": r["day"].strftime("%a"),
                "status": r["status"].replace("_", " ").capitalize(), "_status": r["status"],
                "check_in": timeutil.to_local(r["check_in"], tz).strftime("%H:%M") if r["check_in"] else "",
                "check_out": timeutil.to_local(r["check_out"], tz).strftime("%H:%M") if r["check_out"] else "",
                "late": r["late_minutes"] or "", "worked": _hm(r["payable_minutes"]), "overtime": _hm(r["overtime_minutes"]),
                "note": r["note"] or ("No punch recorded" if r["status"] == "absent" and r["recorded"] is False else ""), "_minutes": r["payable_minutes"] or 0, "_over": r["overtime_minutes"] or 0, "_late": r["late_minutes"] or 0}))
    groups = []
    for emp_id, sheet in sorted(sheets.items(), key=lambda kv: people[kv[0]].full_name):
        emp = people[emp_id]
        rows = [row for _, row in sorted(sheet["rows"], key=lambda item: item[0]) if row["_status"] != "not_yet_due"]
        if not rows:
            continue
        count = lambda *statuses: sum(1 for r in rows if r["_status"] in statuses)  # noqa: E731
        totals = [("Days present", len({r["date"] for r in rows if r["_status"] in PRESENT_STATUSES})), ("Late arrivals", sum(1 for r in rows if r["_late"] and r["_status"] in PRESENT_STATUSES)),
                  ("Week off", count("week_off")), ("Absent", count("absent")), ("On leave", count(*LEAVE_STATUSES)),
                  ("Hours worked", _hm(sum(r["_minutes"] for r in rows)) or "0:00"), ("Overtime", _hm(sum(r["_over"] for r in rows)) or "0:00")]
        for r in rows:
            for private in ("_status", "_minutes", "_over", "_late"):
                del r[private]
        groups.append({
            "title": f"{emp.full_name} ({emp.employee_code})", "layout": "sheet", "page_break": True, "summary_first": True,
            "meta": [("Employee", emp.full_name), ("Employee ID", emp.employee_code), ("Job title", emp.job_title),
                     *([("Company", emp.company)] if emp.company else []),
                     ("Location", ", ".join(sorted(sheet["places"])))],
            "columns": [("date", "Date"), ("weekday", "Day"), ("status", "Status"), ("check_in", "In"), ("check_out", "Out"),
                        ("late", "Late (min)"), ("worked", "Worked"), ("overtime", "Overtime"), ("note", "Note")],
            "rows": rows, "totals": totals})
    return groups


def _hm(minutes: int | None) -> str:
    return "" if minutes is None else f"{minutes // 60}:{minutes % 60:02d}"


def _money(value) -> str:
    return "" if value is None else f"{value:.3f}"


def _receipt_groups(db: Session, locations: list[Location], f: Filters, day_from: date, day_to: date) -> list[dict]:
    names, suppliers = _names(db), {s.id: s.name for s in db.scalars(select(Supplier))}
    items = {i.id: i for i in db.scalars(select(InventoryItem))}
    groups = []
    for loc in locations:
        start, end = _bounds(day_from, day_to, loc.timezone)
        # the range is of the invoice date; a document with no invoice date falls back to the day it was entered
        on, after = datetime.combine(day_from, time(0, 0)), datetime.combine(day_to + timedelta(days=1), time(0, 0))
        stmt = select(Receipt).where(Receipt.location_id == loc.id, or_(
            and_(Receipt.invoice_date.is_not(None), Receipt.invoice_date >= on, Receipt.invoice_date < after),
            and_(Receipt.invoice_date.is_(None), Receipt.received_at >= start, Receipt.received_at < end)))
        if f.supplier_id is not None:
            stmt = stmt.where(Receipt.supplier_id == f.supplier_id)
        docs = list(db.scalars(stmt.order_by(Receipt.received_at)))
        if not docs:
            continue
        rows = []
        lines_by_doc: dict[int, list] = {}  # every line of every document in one query, grouped by document
        for ln in db.scalars(select(ReceiptLine).where(ReceiptLine.receipt_id.in_([d.id for d in docs])).order_by(ReceiptLine.id)):
            lines_by_doc.setdefault(ln.receipt_id, []).append(ln)
        for doc in docs:
            kind = "Return" if doc.doc_type == "supplier_return" else "Receipt"
            for ln in lines_by_doc.get(doc.id, []):
                item = items[ln.item_id]
                rows.append({"date": (doc.received_on or timeutil.to_local(doc.received_at, loc.timezone).date()).strftime("%d %b %Y"), "type": kind, "supplier": suppliers.get(doc.supplier_id, ""),
                             "invoice": doc.invoice_number, "invoice_date": doc.invoice_date.date().isoformat() if doc.invoice_date else "", "item": f"{item.code} - {item.name}", "qty": ln.qty,
                             "unit_cost": _money(ln.unit_cost), "discount": _money(ln.discount_amount), "line_total": _money(ln.line_total),
                             "received_by": names.get(doc.received_by, ""), "status": "Void" if doc.status == "void" else "Posted"})
        posted = [d for d in docs if d.status == "posted" and d.doc_type == "receipt" and d.total is not None]
        sub = sum((d.subtotal or 0 for d in posted), 0)
        disc = sum(((d.line_discount_total or 0) + (d.discount_amount or 0) for d in posted), 0)
        groups.append({
            "title": f"{loc.name} - Receipts and invoices", "meta": [("Location", loc.name)],
            "columns": [("date", "Received"), ("type", "Type"), ("supplier", "Supplier"), ("invoice", "Invoice"), ("invoice_date", "Invoice date"), ("item", "Item"),
                        ("qty", "Qty"), ("unit_cost", "Unit cost"), ("discount", "Discount"), ("line_total", "Line total"),
                        ("received_by", "Received by"), ("status", "Status")],
            "rows": rows,
            "totals": [("Documents", len(docs)), ("Sub total", _money(sub)), ("Total discount", _money(disc)),
                       ("Invoice total (posted receipts)", _money(sum((d.total for d in posted), 0)))]})
    return groups


def _movement_groups(db: Session, locations: list[Location], f: Filters, day_from: date, day_to: date) -> list[dict]:
    names = _names(db)
    items = {i.id: i for i in db.scalars(select(InventoryItem))}
    categories = {c.id: c.name for c in db.scalars(select(InventoryCategory))}
    groups = []
    for loc in locations:
        start, end = _bounds(day_from, day_to, loc.timezone)
        stmt = select(StockTransaction).where(StockTransaction.location_id == loc.id, StockTransaction.occurred_at >= start,
                                              StockTransaction.occurred_at < end)
        if f.movement in MOVEMENTS:
            stmt = stmt.where(StockTransaction.txn_type.in_(MOVEMENTS[f.movement]))
        if f.item_id is not None:
            stmt = stmt.where(StockTransaction.item_id == f.item_id)
        txns = list(db.scalars(stmt.order_by(StockTransaction.occurred_at, StockTransaction.id)))
        if not txns:
            continue
        rows = []
        for t in txns:
            item = items[t.item_id]
            when = _local(t.occurred_at, loc.timezone)
            rows.append({"date": when[:11], "time": when[12:], "item": f"{item.code} - {item.name}", "category": categories.get(item.category_id, ""),
                         "type": t.txn_type.replace("_", " ").capitalize(), "qty": t.qty_delta, "by": names.get(t.user_id, ""),
                         "reason": t.reason or "", "reference": f"{t.ref_type} #{t.ref_id}" if t.ref_type else ""})
        groups.append({
            "title": f"{loc.name} - Stock movements", "meta": [("Location", loc.name)],
            "columns": [("date", "Date"), ("time", "Time"), ("item", "Item"), ("category", "Category"), ("type", "Movement"),
                        ("qty", "Qty"), ("by", "By"), ("reason", "Reason"), ("reference", "Reference")],
            "rows": rows,
            "totals": [("Movements", len(txns)), ("Stock in", sum(t.qty_delta for t in txns if t.qty_delta > 0)),
                       ("Stock out", -sum(t.qty_delta for t in txns if t.qty_delta < 0)), ("Net", sum(t.qty_delta for t in txns))]})
    return groups


def _lot_groups(db: Session, locations: list[Location], f: Filters, day_from: date, day_to: date) -> list[dict]:
    """One table per location of the lots received in the period, with their status and use-by."""
    items = dict(db.execute(select(FoodItem.id, FoodItem.name)).all())
    suppliers = dict(db.execute(select(Supplier.id, Supplier.name)).all())
    groups = []
    for loc in locations:
        start, end = _bounds(day_from, day_to, loc.timezone)
        stmt = select(Lot).where(Lot.location_id == loc.id, Lot.kind == "received", Lot.created_at >= start, Lot.created_at < end)
        if f.food_group:
            stmt = stmt.where(Lot.food_group == f.food_group)
        if f.supplier_id is not None:
            stmt = stmt.where(Lot.supplier_id == f.supplier_id)
        if f.status:
            stmt = stmt.where(Lot.status == f.status)
        lots = list(db.scalars(stmt.order_by(Lot.created_at, Lot.id)))
        if not lots:
            continue
        rows = [{"lot": lot.code, "received": _local(lot.created_at, loc.timezone), "food": items.get(lot.food_item_id, ""),
                 "supplier": suppliers.get(lot.supplier_id, ""), "stored": CONDITIONS[lot.condition],
                 "quantity": f"{lot.qty:f} {lot.unit or ''}".strip() if lot.qty is not None else "",
                 "arrival_temp": "" if lot.temp_c is None else f"{lot.temp_c:f} C", "use_by": _local(lot.use_by, loc.timezone),
                 "status": lot.status.replace("_", " ").capitalize()} for lot in lots]
        groups.append({
            "title": f"{loc.name} - Lot register", "meta": [("Location", loc.name)],
            "columns": [("lot", "Lot"), ("received", "Received"), ("food", "Food"), ("supplier", "Supplier"), ("stored", "Stored as"),
                        ("quantity", "Quantity"), ("arrival_temp", "Arrival temperature"), ("use_by", "Use by"), ("status", "Status")],
            "rows": rows,
            "totals": [("Lots", len(lots))] + [(s.replace("_", " ").capitalize(), sum(1 for lot in lots if lot.status == s)) for s in STATUS_FILTERS["lots"]]})
    return groups


def build_record(db: Session, now: datetime, scope: set[int] | None, kind: str, day_from: date, day_to: date,
                 f: Filters, prepared_by: str) -> dict:
    if kind not in KINDS:
        raise ValueError("Unknown record type")
    if day_from > day_to:
        raise ValueError("The start date is after the end date")
    if (day_to - day_from).days >= MAX_DAYS:
        raise ValueError(f"A record covers at most {MAX_DAYS} days")
    if f.status and f.status not in STATUS_FILTERS.get(kind, ()):
        raise ValueError("Unknown status for this report")
    if f.food_group and f.food_group not in GROUPS:
        raise ValueError("Unknown food group")
    locations = _locations(db, scope, f.location_id)
    if kind == "monitoring":
        groups = _monitoring_groups(db, locations, day_from, day_to, f.equipment_id, f.status, f.equipment_kind)
    elif kind == "lots":
        groups = _lot_groups(db, locations, f, day_from, day_to)
    elif kind == "checklists":
        groups = _checklist_groups(db, locations, day_from, day_to, f.frequency, f.employee_id, f.status, f.template_id)
    elif kind == "checklist_chart":
        groups = _chart_groups(db, now, scope, f, day_from, day_to)
    elif kind == "attendance":
        groups = _attendance_groups(db, now, scope, f, day_from, day_to)
    elif kind == "attendance_sheet":
        groups = _attendance_sheet_groups(db, now, scope, f, day_from, day_to)
    elif kind == "stock_cost":
        groups = _stock_cost_groups(db, locations, day_from, day_to)
    elif kind == "stock_cost_category":
        groups = _stock_cost_category_groups(db, locations, day_from, day_to)
    elif kind == "inventory_detail":
        groups = _inventory_detail_groups(db, locations, day_from, day_to)
    elif kind == "receipts":
        groups = _receipt_groups(db, locations, f, day_from, day_to)
    else:
        groups = _movement_groups(db, locations, f, day_from, day_to)
    label = day_from.strftime("%d %b %Y") if day_from == day_to else f"{day_from.strftime('%d %b %Y')} to {day_to.strftime('%d %b %Y')}"
    return {"kind": kind, "title": KINDS[kind], "period": {"from": day_from.isoformat(), "to": day_to.isoformat(), "label": label},
            "locations": [loc.name for loc in locations], "prepared_by": prepared_by,
            "generated_at": now.strftime("%d %b %Y %H:%M UTC"), "groups": groups}
