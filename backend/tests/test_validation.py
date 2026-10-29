"""Logical and data validation across the modules: every bad input is refused and nothing is written."""
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.models import (BreakageIncident, InventoryItem, InventoryTransfer, Receipt, StockTransaction)

from .helpers import MGR, STEWARD, SUP, SUP_RB, balance, item_id, ledger_sum, loc_id, retire_item
from .test_receiving import receive


def refs(client, h):
    cat = client.get("/api/inventory/categories", headers=h).json()[0]["id"]
    unit = client.get("/api/inventory/units", headers=h).json()[0]["id"]
    return cat, unit


def new_item(client, h, **over):
    cat, unit = refs(client, h)
    return client.post("/api/inventory/items", json={"name": "Probe item", "category_id": cat, "unit_id": unit, **over}, headers=h)


def txn(client, h, db, code="PL-001", loc="MK", **over):
    body = {"item_id": item_id(db, code), "location_id": loc_id(db, loc), "txn_type": "issue", "qty": 1, **over}
    return client.post("/api/inventory/transactions", json=body, headers=h)


# ------------------------------------------------------------------ items

@pytest.mark.parametrize("over", [
    {"min_level": 10, "target_level": 5},                 # the target cannot be below the minimum
    {"opening_qty": 10**9, "opening_location_id": 1},      # absurd quantities
    {"min_level": 10**9},
    {"unit_cost": 10**9},
    {"name": "   "},
    {"description": "x" * 2001},
])
def test_bad_item_data_is_refused(client, login, over):
    assert new_item(client, login(MGR), **over).status_code in (400, 422)


def test_item_updates_are_checked_against_the_stored_levels(client, login, db):
    m = login(MGR)
    plate = item_id(db, "PL-001")  # minimum 60
    assert client.put(f"/api/inventory/items/{plate}", json={"target_level": 10}, headers=m).status_code in (400, 422)
    assert client.put(f"/api/inventory/items/{plate}", json={"min_level": 10**9}, headers=m).status_code == 422
    assert client.put(f"/api/inventory/items/{plate}", json={"name": "  "}, headers=m).status_code in (400, 422)


# ------------------------------------------------------------------ stock transactions

@pytest.mark.parametrize("qty", [0, -5, 10**9])
def test_transaction_quantities_must_be_sensible(client, login, db, qty):
    before = db.scalar(select(func.count()).select_from(StockTransaction))
    assert txn(client, login(SUP), db, txn_type="receipt", qty=qty).status_code in (400, 422)
    assert db.scalar(select(func.count()).select_from(StockTransaction)) == before


def test_stock_cannot_go_negative(client, login, db):  # noqa: C901
    h = login(SUP)
    assert txn(client, h, db, qty=201).status_code in (400, 409)  # 200 on hand
    assert balance(db, "PL-001", "MK") == 200
    assert txn(client, h, db, txn_type="damage", qty=5).status_code in (400, 422)  # a reason is needed
    assert txn(client, login(MGR), db, txn_type="adjustment", qty=-300, reason="Recount of the shelf").status_code in (400, 409)
    assert balance(db, "PL-001", "MK") == ledger_sum(db, "PL-001", "MK") == 200


def test_retired_items_and_foreign_locations_are_refused(client, login, db):
    m = login(MGR)
    retire_item(client, m, db, "PL-002")
    assert txn(client, m, db, code="PL-002", txn_type="receipt", qty=5).status_code in (400, 409)
    assert txn(client, login(SUP_RB), db, loc="MK").status_code == 403
    assert client.post("/api/inventory/transactions", json={"item_id": item_id(db, "PL-001"), "location_id": 9999, "txn_type": "receipt", "qty": 1}, headers=m).status_code in (400, 403, 404)


# ------------------------------------------------------------------ transfers, breakage, receipts

def test_a_transfer_cannot_ask_for_more_than_the_source_holds(client, login, db):
    body = {"from_location_id": loc_id(db, "MK"), "to_location_id": loc_id(db, "BQ"), "lines": [{"item_id": item_id(db, "PL-001"), "qty": 500}]}
    before = db.scalar(select(func.count()).select_from(InventoryTransfer))
    assert client.post("/api/stock/transfers", json=body, headers=login(MGR)).status_code in (400, 409)
    assert db.scalar(select(func.count()).select_from(InventoryTransfer)) == before


def test_breakage_quantities_must_be_sensible(client, login, db):
    h = login(STEWARD)
    base = {"location_id": loc_id(db, "MK"), "item_id": item_id(db, "PL-001"), "incident_type": "breakage"}
    before = db.scalar(select(func.count()).select_from(BreakageIncident))
    for qty in (0, -1, 10**9):
        assert client.post("/api/breakage", json={**base, "qty": qty}, headers=h).status_code in (400, 422), qty
    assert db.scalar(select(func.count()).select_from(BreakageIncident)) == before


def test_receipt_dates_and_items_are_checked(client, login, db):
    h = login(SUP)
    future = (__import__("datetime").date.today() + timedelta(days=30)).isoformat()
    before = db.scalar(select(func.count()).select_from(Receipt))
    assert receive(client, h, db, invoice="V-1", invoice_date=future).status_code in (400, 422)
    assert receive(client, h, db, invoice="V-2", invoice_date="1990-01-01").status_code in (400, 422)
    assert receive(client, h, db, invoice="  ", ).status_code in (400, 422)
    assert receive(client, h, db, [{"item_id": 99999, "qty": 1}], invoice="V-3").status_code in (400, 404)
    assert db.scalar(select(func.count()).select_from(Receipt)) == before


def test_supplier_returns_cannot_exceed_stock(client, login, db):
    assert receive(client, login(SUP), db, [{"item_id": item_id(db, "PL-001"), "qty": 500}], invoice="RET-1", doc_type="supplier_return").status_code in (400, 409)
    assert balance(db, "PL-001", "MK") == 200


# ------------------------------------------------------------------ people, shifts, settings

@pytest.mark.parametrize("over", [
    {"phone": "call me maybe"},
    {"full_name": "   "},
    {"job_title": "x" * 200},
    {"emergency_contact": "x" * 500},
    {"date_joined": "1900-01-01"},
    {"date_joined": "2999-01-01"},
])
def test_bad_employee_data_is_refused(client, login, db, over):
    m = login(MGR)
    emp = next(e["id"] for e in client.get("/api/employees?size=50", headers=m).json()["items"] if e["employee_code"] == "E004")
    assert client.put(f"/api/employees/{emp}", json=over, headers=m).status_code in (400, 422)


def test_new_employee_is_validated(client, login, db):
    m = login(MGR)
    base = {"employee_code": "E900", "full_name": "Test Person", "job_title": "Steward", "email": "test.person@example.com",
            "password": "a-strong-password-1", "role": "steward", "location_ids": [loc_id(db, "MK")]}
    assert client.post("/api/employees", json={**base, "phone": "abc"}, headers=m).status_code == 422
    assert client.post("/api/employees", json={**base, "employee_code": "E 9 0 0"}, headers=m).status_code in (400, 422)
    assert client.post("/api/employees", json={**base, "password": "short"}, headers=m).status_code == 422
    assert client.post("/api/employees", json={**base, "password": "aaaaaaaaaaaa"}, headers=m).status_code in (400, 422)  # no variety
    assert client.post("/api/employees", json=base, headers=m).status_code == 201


def test_shift_times_are_checked(client, login):
    m = login(MGR)
    body = {"name": "Odd shift", "start_time": "09:00:00", "end_time": "09:00:00", "grace_minutes": 10, "break_minutes": 0}
    assert client.post("/api/roster/shifts", json=body, headers=m).status_code in (400, 422)  # no length
    assert client.post("/api/roster/shifts", json={**body, "end_time": "10:00:00", "break_minutes": 90}, headers=m).status_code in (400, 422)  # break longer than the shift
    assert client.post("/api/roster/shifts", json={**body, "end_time": "17:00:00"}, headers=m).status_code == 201


@pytest.mark.parametrize("values", [{"temp.due_grace_minutes": 10**12}, {"approval.checklists": 2}, {"temp.retest_minutes": -1}])
def test_settings_values_are_bounded(client, login, values):
    assert client.put("/api/settings", json={"values": values}, headers=login(MGR)).status_code in (400, 422)
