from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import timeutil
from ..models import (BreakageIncident, CorrectiveAction, Employee, Equipment, InventoryItem, StockTransaction,
                      TemperatureReading)
from . import metrics
from .monitoring import CLOSED_ACTIONS, describe
from .reference import user_names
from .inventory import reconcile
from .settings import get_setting
from .summary import pending_items

PERIODS = ("daily", "weekly", "monthly")


@dataclass
class Ctx:
    db: Session
    now: datetime
    wins: list
    scope: set[int] | None
    d_from: date
    d_to: date
    employee_id: int | None
    names_by_user: dict
    items: dict


def section(sid: str, title: str, columns: list[tuple[str, str]], rows: list[dict], totals: list[tuple[str, object]] | None = None) -> dict:
    return {"id": sid, "title": title, "columns": [{"key": k, "label": label} for k, label in columns], "rows": rows,
            "totals": [{"label": label, "value": value} for label, value in (totals or [])]}


def local(dt: datetime | None, tz: str, fmt: str = "%Y-%m-%d %H:%M") -> str | None:
    return timeutil.to_local(dt, tz).strftime(fmt) if dt else None


def hours(minutes: int | None) -> str | None:
    return None if minutes is None else f"{minutes // 60}:{minutes % 60:02d}"


def ratio(num: int, den: int) -> str:
    return f"{num}/{den} ({metrics.pct(num, den)}%)" if den else f"{num}/{den} (n/a)"


def period_bounds(period: str, anchor: date) -> tuple[date, date, str]:
    if period == "daily":
        return anchor, anchor, anchor.isoformat()
    if period == "weekly":
        start, end = metrics.week_of(anchor)
        return start, end, f"Week {start.isoformat()} to {end.isoformat()}"
    first = anchor.replace(day=1)
    following = (first + timedelta(days=32)).replace(day=1)
    return first, following - timedelta(days=1), first.strftime("%B %Y")


# ---------------------------------------------------------------- daily / shared sections

def sec_attendance(c: Ctx) -> dict:
    rows, totals = [], Counter()
    for w in c.wins:
        stats = metrics.attendance_stats(c.db, w, c.now, c.employee_id)
        for key in ("scheduled", "present", "late", "absent", "on_leave", "week_off"):
            totals[key] += stats[key]
        tz = w.loc.timezone
        rows += [{"location": w.loc.name, "date": r["day"].isoformat(), "employee": r["name"], "shift": r["shift"],
                  "status": r["status"], "recorded": {True: "Yes", False: "No", None: ""}[r["recorded"]], "note": r["note"],
                  "check_in": local(r["check_in"], tz), "check_out": local(r["check_out"], tz),
                  "late": r["late_minutes"], "worked": hours(r["payable_minutes"]), "overtime": hours(r["overtime_minutes"])}
                 for r in stats["rows"]]
    cols = [("location", "Location"), ("date", "Date"), ("employee", "Employee"), ("shift", "Shift"), ("status", "Status"),
            ("recorded", "Recorded"), ("note", "Note"), ("check_in", "Check-in"), ("check_out", "Check-out"), ("late", "Late (min)"), ("worked", "Worked (h:mm)"),
            ("overtime", "Overtime (h:mm)")]
    return section("attendance", "Employee attendance and shift coverage", cols, rows,
                   [("Scheduled", totals["scheduled"]), ("Present", ratio(totals["present"], totals["scheduled"])),
                    ("Late arrivals", totals["late"]), ("Absent", totals["absent"]), ("On leave (excluded)", totals["on_leave"]),
                    ("Week off (excluded)", totals["week_off"])])


def sec_checklists(c: Ctx) -> dict:
    rows, counts = [], Counter()
    for w in c.wins:
        stats = metrics.checklist_stats(c.db, w, c.now, c.employee_id)
        counts.update(stats["counts"])
        tz = w.loc.timezone
        rows += [{"location": w.loc.name, "date": inst.local_date.isoformat(), "task": task.description,
                  "category": tpl.category, "status": state, "due": local(inst.due_at, tz),
                  "completed_at": local(inst.completed_at, tz), "completed_by": c.names_by_user.get(inst.completed_by),
                  "verified_by": c.names_by_user.get(inst.verified_by)}
                 for inst, task, tpl, state in stats["rows"]]
    comp = metrics.compliance(counts)
    cols = [("location", "Location"), ("date", "Date"), ("task", "Task"), ("category", "Category"), ("status", "Status"),
            ("due", "Due"), ("completed_at", "Completed"), ("completed_by", "By"), ("verified_by", "Verified by")]
    return section("checklists", "Checklist completion and overdue activities", cols, rows,
                   [("Compliance", ratio(comp["numerator"], comp["denominator"])), ("Completed", counts["completed"]),
                    ("Verified", counts["verified"]), ("Pending verification", counts["pending_verification"]),
                    ("Waived (excluded)", counts["waived"]), ("Overdue", counts["overdue"]), ("Failed", counts["failed"]),
                    ("Not yet due (excluded)", counts["upcoming"])])


def _readings(c: Ctx):
    for w in c.wins:
        for r in c.db.scalars(select(TemperatureReading).where(
                TemperatureReading.location_id == w.loc.id, TemperatureReading.recorded_at >= w.start,
                TemperatureReading.recorded_at < w.end).order_by(TemperatureReading.recorded_at)):
            yield w, r


def sec_monitoring_log(c: Ctx) -> dict:
    eq = {e.id: e.name for e in c.db.scalars(select(Equipment))}
    actions = {a.reading_id: a.status for a in c.db.scalars(select(CorrectiveAction))}
    rows = []
    for w, r in _readings(c):
        rows.append({"location": w.loc.name, "time": local(r.recorded_at, w.loc.timezone), "equipment": eq.get(r.equipment_id),
                     "parameter": r.parameter, "stage": r.stage, "source": r.source,
                     "value": describe(r), "reference": r.reference,
                     "limits": f"{r.min_limit if r.min_limit is not None else '-'} to {r.max_limit if r.max_limit is not None else '-'}",
                     "result": "Pass" if r.passed else "FAIL", "retest": "Yes" if r.retest_of_id else "",
                     "recorded_by": c.names_by_user.get(r.recorded_by), "action": actions.get(r.id)})
    cols = [("location", "Location"), ("time", "Time"), ("equipment", "Monitoring point"), ("stage", "Check"), ("source", "Source"),
            ("parameter", "Measure"), ("value", "Value"), ("limits", "Limits"), ("reference", "Reference"), ("result", "Result"), ("retest", "Retest"),
            ("recorded_by", "Recorded by"), ("action", "Corrective action")]
    return section("monitoring", "Monitoring log", cols, rows,
                   [("Readings", len(rows)), ("Failed", sum(1 for r in rows if r["result"] == "FAIL"))])


def _incidents(c: Ctx):
    for w in c.wins:
        for inc in c.db.scalars(select(BreakageIncident).where(
                BreakageIncident.location_id == w.loc.id, BreakageIncident.occurred_at >= w.start,
                BreakageIncident.occurred_at < w.end).order_by(BreakageIncident.id)):
            yield w, inc


def sec_breakage_log(c: Ctx) -> dict:
    rows = [{"code": i.code, "location": w.loc.name, "time": local(i.occurred_at, w.loc.timezone),
             "item": c.items[i.item_id].name, "qty": i.qty, "type": i.incident_type, "status": i.status,
             "cost": float(i.est_cost) if i.est_cost is not None else None, "reason": i.reason}
            for w, i in _incidents(c)]
    cols = [("code", "Incident"), ("location", "Location"), ("time", "Time"), ("item", "Item"), ("qty", "Qty"),
            ("type", "Type"), ("status", "Status"), ("cost", "Est. cost"), ("reason", "Reason")]
    counted = [r for r in rows if r["status"] != "rejected"]
    return section("breakage", "Breakage and damage incidents", cols, rows,
                   [("Incidents (excluding rejected)", len(counted)), ("Units", sum(r["qty"] for r in counted)),
                    ("Estimated cost", round(sum(r["cost"] or 0 for r in counted), 3))])


def sec_inventory_movements(c: Ctx) -> dict:
    rows = []
    for w in c.wins:
        for t in c.db.scalars(select(StockTransaction).where(
                StockTransaction.location_id == w.loc.id, StockTransaction.occurred_at >= w.start,
                StockTransaction.occurred_at < w.end).order_by(StockTransaction.id)):
            rows.append({"time": local(t.occurred_at, w.loc.timezone), "location": w.loc.name, "item": c.items[t.item_id].name,
                         "type": metrics.movement_kind(t.txn_type, t.ref_type), "qty": t.qty_delta, "by": c.names_by_user.get(t.user_id), "reason": t.reason})
    totals = defaultdict(int)
    for r in rows:
        totals[r["type"]] += r["qty"]
    cols = [("time", "Time"), ("location", "Location"), ("item", "Item"), ("type", "Type"), ("qty", "Qty"), ("by", "By"),
            ("reason", "Reason")]
    return section("inventory", "Inventory receipts, issues and transfers", cols, rows,
                   [(k.replace("_", " ").title(), v) for k, v in sorted(totals.items())])


# ---------------------------------------------------------------- weekly / monthly sections

def sec_checklist_by_location(c: Ctx) -> dict:
    rows, total = [], Counter()
    for w in c.wins:
        stats = metrics.checklist_stats(c.db, w, c.now, c.employee_id)
        cn = stats["counts"]
        total.update(cn)
        rows.append({"location": w.loc.name, "done": stats["numerator"], "due": stats["denominator"], "overdue": cn["overdue"],
                     "failed": cn["failed"], "pending": cn["pending_verification"], "waived": cn["waived"],
                     "percent": stats["percent"]})
    comp = metrics.compliance(total)
    cols = [("location", "Location"), ("done", "Done (numerator)"), ("due", "Due (denominator)"), ("overdue", "Overdue"),
            ("failed", "Failed"), ("pending", "Pending verification"), ("waived", "Waived"), ("percent", "Compliance %")]
    return section("checklist_by_location", "Checklist compliance by location", cols, rows,
                   [("Organization", ratio(comp["numerator"], comp["denominator"]))])


def sec_attendance_trend(c: Ctx) -> dict:
    per_day: dict[date, Counter] = defaultdict(Counter)
    for w in c.wins:
        for day, vals in metrics.attendance_stats(c.db, w, c.now, c.employee_id)["per_day"].items():
            per_day[day].update(vals)
    rows = [{"date": d.isoformat(), **{k: per_day[d][k] for k in metrics.ATTENDANCE_KEYS},
             "percent": metrics.pct(per_day[d]["present"], per_day[d]["scheduled"])} for d in sorted(per_day)]
    cols = [("date", "Date"), ("scheduled", "Scheduled"), ("present", "Present"), ("late", "Late"), ("absent", "Absent"),
            ("on_leave", "On leave"), ("week_off", "Week off"), ("percent", "Attendance %")]
    return section("attendance_trend", "Attendance trend", cols, rows)


def sec_monitoring_compliance(c: Ctx) -> dict:
    rows = []
    for w in c.wins:
        for e in metrics.monitoring_stats(c.db, w, c.now)["equipment"].values():
            rows.append({"location": e["location"], "equipment": e["equipment"], "due": e["due"], "done": e["done"],
                         "missed": e["missed"], "percent": metrics.pct(e["done"], e["due"]), "failed": e["failed"]})
    cols = [("location", "Location"), ("equipment", "Monitoring point"), ("due", "Checks due (denominator)"),
            ("done", "Recorded (numerator)"), ("missed", "Missed"), ("percent", "Compliance %"), ("failed", "Failed readings")]
    due, done = sum(r["due"] for r in rows), sum(r["done"] for r in rows)
    return section("monitoring_compliance", "Monitoring compliance", cols, rows,
                   [("Overall", ratio(done, due)), ("Failed readings", sum(r["failed"] for r in rows))])


def sec_equipment_failures(c: Ctx) -> dict:
    eq = {e.id: e for e in c.db.scalars(select(Equipment))}
    failed: Counter = Counter()
    for _, r in _readings(c):
        if not r.passed:
            failed[r.equipment_id] += 1
    unresolved: Counter = Counter()
    for action, reading in c.db.execute(select(CorrectiveAction, TemperatureReading).join(
            TemperatureReading, TemperatureReading.id == CorrectiveAction.reading_id).where(
            CorrectiveAction.status.not_in(CLOSED_ACTIONS))).all():
        unresolved[reading.equipment_id] += 1
    repeat = get_setting(c.db, "temp.repeat_failure_count")
    place = {w.loc.id: w.loc.name for w in c.wins}
    rows = [{"location": place.get(eq[i].location_id), "equipment": eq[i].name, "failed": n, "unresolved": unresolved[i],
             "repeat": "Yes" if n >= repeat else ""} for i, n in failed.most_common()]
    cols = [("location", "Location"), ("equipment", "Equipment"), ("failed", "Failed readings"),
            ("unresolved", "Unresolved actions"), ("repeat", "Repeat failure")]
    return section("equipment_failures", "Failed readings and repeat failures by monitoring point", cols, rows,
                   [("Total failed readings", sum(failed.values()))])


def sec_recurring_overdue(c: Ctx) -> dict:
    counter: Counter = Counter()
    for w in c.wins:
        for inst, task, _, state in metrics.checklist_stats(c.db, w, c.now)["rows"]:
            if state in ("overdue", "failed"):
                counter[(w.loc.name, task.description)] += 1
    rows = [{"location": loc, "task": task, "times": n} for (loc, task), n in counter.most_common() if n >= 2]
    return section("recurring_overdue", "Recurring overdue tasks (two or more times)",
                   [("location", "Location"), ("task", "Task"), ("times", "Times overdue or failed")], rows)


def sec_breakage_summary(c: Ctx) -> dict:
    by_item: dict[str, dict] = {}
    for _, i in _incidents(c):
        if i.status == "rejected":
            continue
        e = by_item.setdefault(c.items[i.item_id].name, {"item": c.items[i.item_id].name, "incidents": 0, "qty": 0, "cost": 0.0})
        e["incidents"] += 1
        e["qty"] += i.qty
        e["cost"] += float(i.est_cost or 0)
    rows = sorted(by_item.values(), key=lambda r: -r["qty"])
    for r in rows:
        r["cost"] = round(r["cost"], 3)
    return section("breakage_summary", "Breakage and damage by item",
                   [("item", "Item"), ("incidents", "Incidents"), ("qty", "Units"), ("cost", "Estimated cost")], rows,
                   [("Units", sum(r["qty"] for r in rows)), ("Estimated cost", round(sum(r["cost"] for r in rows), 3))])


def sec_inventory_variance(c: Ctx) -> dict:
    net: dict[tuple[str, str], int] = defaultdict(int)
    for w in c.wins:
        for t in c.db.scalars(select(StockTransaction).where(
                StockTransaction.location_id == w.loc.id, StockTransaction.txn_type == "adjustment",
                StockTransaction.occurred_at >= w.start, StockTransaction.occurred_at < w.end)):
            net[(w.loc.name, c.items[t.item_id].name)] += t.qty_delta
    rows = [{"location": loc, "item": item, "variance": v} for (loc, item), v in sorted(net.items())]
    return section("inventory_variance", "Inventory variance (posted adjustments)",
                   [("location", "Location"), ("item", "Item"), ("variance", "Net adjustment")], rows,
                   [("Net units", sum(r["variance"] for r in rows))])


def sec_attendance_hours(c: Ctx) -> dict:
    agg: dict[str, Counter] = defaultdict(Counter)
    counted: set = set()  # a day worked at two outlets is one day
    for w in c.wins:
        for r in metrics.attendance_stats(c.db, w, c.now, c.employee_id)["rows"]:
            a = agg[r["name"]]
            if r["status"] == "absent":
                a["absent"] += 1
                a["unrecorded"] += 1 if r["recorded"] is False else 0
            elif r["status"] in metrics.LEAVE_TYPES:
                a["leave"] += 1
            elif r["status"] == "week_off":
                a["weekoff"] += 1
            elif r["check_in"]:
                a["days"] += 0 if (r["name"], r["day"]) in counted else 1
                counted.add((r["name"], r["day"]))
                a["minutes"] += r["payable_minutes"] or 0
                a["overtime"] += r["overtime_minutes"] or 0
                a["late"] += 1 if r["late_minutes"] > 0 else 0
                a["missed"] += 1 if r["status"] == "missed_checkout" else 0
    rows = [{"employee": n, "days": a["days"], "hours": hours(a["minutes"]), "overtime": hours(a["overtime"]),
             "late": a["late"], "absent": a["absent"], "unrecorded": a["unrecorded"], "leave": a["leave"],
             "weekoff": a["weekoff"], "missed": a["missed"]} for n, a in sorted(agg.items())]
    return section("attendance_hours", "Attendance and total working hours",
                   [("employee", "Employee"), ("days", "Days worked"), ("hours", "Hours worked (h:mm)"),
                    ("overtime", "Overtime (h:mm)"), ("late", "Late days"), ("absent", "Absences"),
                    ("unrecorded", "of which not recorded"), ("leave", "Leave days"), ("weekoff", "Week-off days"),
                    ("missed", "Missed check-outs")], rows)


def sec_corrective_actions(c: Ctx) -> dict:
    actions = {a.reading_id: a for a in c.db.scalars(select(CorrectiveAction))}
    eq = {e.id: e.name for e in c.db.scalars(select(Equipment))}
    rows = []
    for w, r in _readings(c):
        if r.passed:
            continue
        a = actions.get(r.id)
        minutes = int((a.resolved_at - r.recorded_at).total_seconds() // 60) if a and a.resolved_at else None
        rows.append({"location": w.loc.name, "time": local(r.recorded_at, w.loc.timezone), "equipment": eq.get(r.equipment_id),
                     "stage": r.stage, "value": describe(r), "status": a.status if a else "none",
                     "action": a.action if a else None, "minutes_to_resolve": minutes})
    return section("corrective_actions", "Failed readings and corrective actions",
                   [("location", "Location"), ("time", "Time"), ("equipment", "Equipment"), ("stage", "Stage"),
                    ("value", "Value"), ("status", "Action status"), ("action", "Action taken"),
                    ("minutes_to_resolve", "Minutes to resolve")], rows,
                   [("Failed readings", len(rows)), ("Resolved", sum(1 for r in rows if r["status"] == "resolved"))])


def sec_reconciliation(c: Ctx) -> dict:
    month = c.d_from.strftime("%Y-%m")
    rows = []
    for w in c.wins:
        for r in reconcile(c.db, w.loc, month):
            rows.append({"location": w.loc.name, "item": f"{r['code']} {r['name']}", "opening": r["opening"],
                         "in": r["opening_stock"] + r["receipts"] + r["returns"] + r["transfers_in"],
                         "out": r["issues"] + r["breakage_damage"] + r["transfers_out"], "adjustments": r["adjustments"],
                         "closing": r["closing"], "counted": r["counted_qty"], "variance": r["count_variance"], "value": r["value"]})
    return section("reconciliation", "Stock reconciliation",
                   [("location", "Location"), ("item", "Item"), ("opening", "Opening"), ("in", "In"),
                    ("out", "Out"), ("adjustments", "Adjustments"), ("closing", "Closing"), ("counted", "Counted"),
                    ("variance", "Count variance"), ("value", "Value")], rows,
                   [("Closing units", sum(r["closing"] for r in rows))])


def sec_stock_consumption(c: Ctx) -> dict:
    agg: dict[tuple[str, str], Counter] = defaultdict(Counter)
    for t in metrics.movements(c.db, c.wins):
        loc = next(w.loc.name for w in c.wins if w.loc.id == t.location_id)
        a = agg[(loc, c.items[t.item_id].name)]
        if t.txn_type in ("issue", "breakage", "damage"):
            a["consumed"] += -t.qty_delta
        elif t.txn_type == "transfer_in":
            a["transfer_in"] += t.qty_delta
        elif t.txn_type == "transfer_out":
            a["transfer_out"] += -t.qty_delta
        elif t.txn_type in ("receipt", "receipt_void"):
            a["received"] += t.qty_delta
    rows = [{"location": loc, "item": item, **{k: a[k] for k in ("received", "consumed", "transfer_in", "transfer_out")}}
            for (loc, item), a in sorted(agg.items())]
    return section("stock_consumption", "Stock consumption and transfer history",
                   [("location", "Location"), ("item", "Item"), ("received", "Received"), ("consumed", "Consumed"),
                    ("transfer_in", "Transferred in"), ("transfer_out", "Transferred out")], rows)


def sec_replenishment(c: Ctx) -> dict:
    snap = metrics.stock_snapshot(c.db, c.scope)
    place = {w.loc.id: w.loc.name for w in c.wins}
    rows = [{"location": place.get(i["location_id"]), "item": i["name"], "qty": i["qty"], "minimum": i["min_level"],
             "target": i["target_level"], "order": max((i["target_level"] or i["min_level"]) - i["qty"], 0)}
            for i in snap["low"] if i["location_id"] in place]
    return section("replenishment", "Low stock and replenishment required",
                   [("location", "Location"), ("item", "Item"), ("qty", "In stock"), ("minimum", "Minimum"),
                    ("target", "Target"), ("order", "Suggested order")], rows,
                   [("Items below minimum", len(rows))])


def sec_outstanding(c: Ctx) -> dict:
    ids = {w.loc.id for w in c.wins}
    items = pending_items(c.db, ids, c.now)
    by: dict[str, list[int]] = defaultdict(list)
    for i in items:
        by[i["category"]].append(i["overdue_minutes"])
    rows = [{"category": k.replace("_", " ").title(), "count": len(v), "oldest_hours": round(max(v) / 60, 1)} for k, v in sorted(by.items())]
    return section("outstanding_issues", "Outstanding issues and corrective-action status",
                   [("category", "Category"), ("count", "Open"), ("oldest_hours", "Oldest (hours)")], rows,
                   [("Total open", len(items))])


def sec_scorecard(c: Ctx) -> dict:
    rows = []
    snap = metrics.stock_snapshot(c.db, c.scope)
    for w in c.wins:
        att = metrics.attendance_stats(c.db, w, c.now)
        chk = metrics.checklist_stats(c.db, w, c.now)
        tmp = metrics.monitoring_stats(c.db, w, c.now)
        incidents = [i for ww, i in _incidents(Ctx(c.db, c.now, [w], c.scope, c.d_from, c.d_to, None, c.names_by_user, c.items))
                     if i.status != "rejected"]
        issues = pending_items(c.db, {w.loc.id}, c.now)
        rows.append({"location": w.loc.name, "attendance": ratio(att["present"], att["scheduled"]),
                     "checklists": ratio(chk["numerator"], chk["denominator"]), "monitoring": ratio(tmp["done"], tmp["due"]),
                     "failed": tmp["failed"], "breakage": sum(i.qty for i in incidents),
                     "breakage_cost": round(sum(float(i.est_cost or 0) for i in incidents), 3),
                     "low_stock": sum(1 for i in snap["low"] if i["location_id"] == w.loc.id), "open_issues": len(issues)})
    return section("scorecard", "Location operational scorecard",
                   [("location", "Location"), ("attendance", "Attendance"), ("checklists", "Checklists"),
                    ("monitoring", "Monitoring checks"), ("failed", "Failed readings"), ("breakage", "Breakage units"),
                    ("breakage_cost", "Breakage cost"), ("low_stock", "Low-stock items"), ("open_issues", "Open issues")], rows)


REPORTS = {
    "daily": [sec_attendance, sec_checklists, sec_monitoring_log, sec_breakage_log, sec_inventory_movements],
    "weekly": [sec_checklist_by_location, sec_attendance_trend, sec_monitoring_compliance, sec_equipment_failures,
               sec_recurring_overdue, sec_breakage_summary, sec_inventory_variance],
    "monthly": [sec_attendance_hours, sec_checklist_by_location, sec_monitoring_compliance, sec_corrective_actions,
                sec_breakage_summary, sec_reconciliation, sec_stock_consumption, sec_replenishment, sec_outstanding,
                sec_scorecard],
}


def build_report(db: Session, now: datetime, scope: set[int] | None, period: str, anchor: date | None,
                 location_id: int | None, employee_id: int | None) -> dict:
    first = metrics.windows_by(db, now, scope, location_id, lambda t: (t, t))
    if not first:
        raise ValueError("No locations in scope")
    d_from, d_to, label = period_bounds(period, anchor or first[0].today)
    wins = metrics.windows(db, now, scope, location_id, d_from, d_to)
    names = user_names(db)
    items = {i.id: i for i in db.scalars(select(InventoryItem))}
    ctx = Ctx(db, now, wins, scope, d_from, d_to, employee_id, names, items)
    sections = [fn(ctx) for fn in REPORTS[period]]
    return {"period": {"type": period, "label": label, "from": d_from.isoformat(), "to": d_to.isoformat()},
            "locations": [w.loc.name for w in wins], "timezones": sorted({w.loc.timezone for w in wins}),
            "generated_at": now.isoformat() + "Z", "sections": sections}
