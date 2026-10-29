import random
from datetime import date, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import (AttendanceRecord, BreakageIncident, ChecklistInstance, InventoryBalance, InventoryItem, Notification,
                        StockTransaction, TemperatureReading)

from .helpers import MGR, STEWARD, STEWARD_RB, SUP, SUP_RB, balance, item_id, ledger_sum, loc_id


def employee_id(client, login, code):
    return next(e["id"] for e in client.get("/api/employees?size=50", headers=login(MGR)).json()["items"]
                if e["employee_code"] == code)


def test_database_refuses_two_open_attendance_records_for_one_employee(db, client, login):
    emp = employee_id(client, login, "E004")
    for _ in range(2):
        db.add(AttendanceRecord(employee_id=emp, location_id=loc_id(db, "MK"), local_date=date(2026, 3, 2),
                                check_in_at=datetime(2026, 3, 2, 2, 0), open_flag=1))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    for _ in range(2):  # closed records (open_flag NULL) may repeat
        db.add(AttendanceRecord(employee_id=emp, location_id=loc_id(db, "MK"), local_date=date(2026, 3, 2),
                                check_in_at=datetime(2026, 3, 2, 2, 0), open_flag=None))
    db.commit()


def test_database_refuses_duplicate_scheduled_task_instances(db, client, login, clock):
    client.post("/api/checklists/generate", json={"location_id": loc_id(db, "MK")}, headers=login(MGR))
    existing = db.scalars(select(ChecklistInstance)).first()
    db.add(ChecklistInstance(task_id=existing.task_id, location_id=existing.location_id, local_date=existing.local_date,
                             shift_key=existing.shift_key))
    with pytest.raises(IntegrityError):
        db.commit()


def test_database_refuses_duplicate_notification_for_the_same_event(db, client, login):
    from app.models import User

    user = db.scalar(select(User))
    db.add(Notification(user_id=user.id, kind="x", title="a", dedupe_key="same"))
    db.commit()
    db.add(Notification(user_id=user.id, kind="x", title="b", dedupe_key="same"))
    with pytest.raises(IntegrityError):
        db.commit()


def test_database_refuses_two_incidents_sharing_one_stock_transaction(db, client, login):
    base = dict(occurred_at=datetime(2026, 3, 2), location_id=loc_id(db, "MK"), item_id=item_id(db, "PL-001"), qty=1,
                incident_type="breakage", reported_by=1)
    txn = db.scalar(select(StockTransaction))
    db.add(BreakageIncident(code="A", transaction_id=txn.id, **base))
    db.commit()
    db.add(BreakageIncident(code="B", transaction_id=txn.id, **base))
    with pytest.raises(IntegrityError):
        db.commit()


def test_monitoring_readings_have_no_update_or_delete_route(client, login, db, clock):
    h = login(STEWARD)
    eq = next(e for e in client.get("/api/monitoring/equipment", headers=h).json() if e["code"] == "DW-MK-1")
    wash = next(s for s in eq["schedules"] if s["stage"] == "wash")
    reading = client.post("/api/monitoring/readings", headers=h, json={"equipment_id": eq["id"], "schedule_id": wash["id"], "value": 20}).json()
    for method in ("put", "patch", "delete"):
        r = getattr(client, method)(f"/api/monitoring/readings/{reading['id']}", headers=login(MGR))
        assert r.status_code in (404, 405)
    assert db.get(TemperatureReading, reading["id"]).passed is False


def test_random_stock_operations_keep_balances_equal_to_the_ledger(client, login, db, clock):
    rng = random.Random(20260302)
    items = ["PL-001", "BW-001", "UT-001", "PN-001"]
    sites = ["MK", "BQ"]
    successes = 0
    for _ in range(60):
        code, site = rng.choice(items), rng.choice(sites)
        kind = rng.choice(["receipt", "issue", "return", "damage", "adjustment", "transfer"])
        if kind == "transfer":
            r = client.post("/api/stock/transfers", headers=login(MGR), json={
                "from_location_id": loc_id(db, site), "to_location_id": loc_id(db, "RB"),
                "lines": [{"item_id": item_id(db, code), "qty": rng.randint(1, 40)}]})
        else:
            qty = rng.randint(1, 40)
            r = client.post("/api/inventory/transactions", headers=login(MGR), json={
                "item_id": item_id(db, code), "location_id": loc_id(db, site), "txn_type": kind,
                "qty": qty * rng.choice([1, -1]) if kind == "adjustment" else qty, "reason": "random exercise run"})
        successes += r.status_code in (200, 201)
        assert r.status_code in (200, 201, 409), r.text
    assert successes > 30
    for bal in db.scalars(select(InventoryBalance)):
        code = db.get(InventoryItem, bal.item_id).code
        site = next(s for s in ("MK", "BQ", "RB") if loc_id(db, s) == bal.location_id)
        assert bal.qty == ledger_sum(db, code, site), f"{code}@{site} drifted from the ledger"
        assert bal.qty >= 0, "refused operations must never leave a negative balance"


def test_failed_stock_operation_rolls_back_completely(client, login, db):
    before = db.scalars(select(StockTransaction.id)).all()
    r = client.post("/api/stock/transfers", headers=login(MGR), json={
        "from_location_id": loc_id(db, "RB"), "to_location_id": loc_id(db, "MK"),
        "lines": [{"item_id": item_id(db, "PL-001"), "qty": 10}, {"item_id": item_id(db, "UT-001"), "qty": 999}]})
    assert r.status_code == 409
    db.expire_all()
    assert db.scalars(select(StockTransaction.id)).all() == before
    assert balance(db, "PL-001", "RB") == 40 and balance(db, "PL-001", "MK") == 200


def test_london_checklist_deadlines_follow_daylight_saving(client, login, db, clock):
    rb = loc_id(db, "RB")

    def deadline(day_utc):
        clock.set(*day_utc)
        client.post("/api/checklists/generate", json={"location_id": rb}, headers=login(MGR))
        items = client.get(f"/api/checklists/instances?location_id={rb}&day={day_utc[0]}-{day_utc[1]:02d}-{day_utc[2]:02d}&size=200",
                           headers=login(MGR)).json()["items"]
        return next(i for i in items if i["frequency"] == "daily")["due_at"]

    assert deadline((2026, 3, 28, 8, 0)) == "2026-03-28T13:30:00Z"   # GMT: local 13:30 is 13:30 UTC
    assert deadline((2026, 3, 29, 8, 0)) == "2026-03-29T12:30:00Z"   # BST begins: local 13:30 is 12:30 UTC


def test_night_shift_crossing_midnight_is_paid_and_dated_correctly(client, login, db, clock):
    m = login(MGR)
    night = client.post("/api/roster/shifts", headers=m, json={"name": "Night", "start_time": "22:00:00", "end_time": "06:00:00",
                                                                "grace_minutes": 10, "break_minutes": 30}).json()
    emp = employee_id(client, login, "E004")
    client.post("/api/roster/assignments", headers=m, json={"employee_id": emp, "shift_id": night["id"], "location_id": loc_id(db, "MK"),
                                                            "weekdays": [0], "valid_from": "2026-03-01"})
    clock.set(2026, 3, 2, 18, 5)  # Monday 22:05 in Dubai
    h = login(STEWARD)
    record = client.post("/api/attendance/check-in", json={"location_id": loc_id(db, "MK")}, headers=h).json()
    assert record["shift_id"] == night["id"] and record["late_minutes"] == 0 and record["local_date"] == "2026-03-02"
    clock.set(2026, 3, 3, 2, 10)  # Tuesday 06:10 in Dubai
    done = client.post("/api/attendance/check-out", json={}, headers=h).json()
    assert done["local_date"] == "2026-03-02" and done["payable_minutes"] == 485 - 30 and done["overtime_minutes"] == 5


def test_monitoring_readings_land_on_the_correct_local_day_around_a_clock_change(client, login, db, clock):
    h = login(STEWARD_RB)
    eq = next(e for e in client.get("/api/monitoring/equipment", headers=h).json() if e["code"] == "GW-RB-1")
    wash = client.post(f"/api/equipment/{eq['id']}/schedules", headers=login(MGR), json={
        "stage": "spot check", "timing": "manual", "min_value": 0, "max_value": 100}).json()
    for moment in ((2026, 3, 29, 0, 30), (2026, 3, 29, 23, 30)):  # 00:30 GMT on the 29th, 00:30 BST on the 30th
        clock.set(*moment)
        client.post("/api/monitoring/readings", headers=h, json={"equipment_id": eq["id"], "schedule_id": wash["id"], "value": 60})
    clock.set(2026, 3, 30, 8, 0)
    for day, expected in (("2026-03-29", 1), ("2026-03-30", 1)):
        report = client.get(f"/api/reports/daily?anchor={day}&location_id={loc_id(db, 'RB')}", headers=login(MGR)).json()
        section = next(s for s in report["sections"] if s["id"] == "monitoring")
        assert len(section["rows"]) == expected, day
    assert client.get(f"/api/reports/daily?anchor=2026-03-29&location_id={loc_id(db, 'RB')}", headers=login(SUP_RB)).status_code == 200
    assert client.get(f"/api/reports/daily?anchor=2026-03-29&location_id={loc_id(db, 'RB')}", headers=login(SUP)).status_code == 403
