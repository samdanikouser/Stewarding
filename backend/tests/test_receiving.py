import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.models import AuditLog, InventoryItem, Receipt, StockTransaction

from .conftest import PASSWORD
from .helpers import MGR, STEWARD, SUP, SUP_RB, balance, item_id, ledger_sum, loc_id, retire_item


def manager_headers(client):
    r = client.post("/api/auth/login", json={"email": MGR, "password": PASSWORD})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def suppliers(client):
    return {s["name"]: s["id"] for s in client.get("/api/suppliers", headers=manager_headers(client)).json()}


def receive(client, h, db, lines=None, invoice="INV-1001", site="MK", supplier="Gulf Catering Supplies", **over):
    lines = lines or [{"item_id": item_id(db, "PL-001"), "qty": 24, "unit_cost": 2.75}]
    body = {"supplier_id": suppliers(client)[supplier], "location_id": loc_id(db, site),
            "invoice_number": invoice, "lines": lines, **over}
    return client.post("/api/receipts", json=body, headers=h)


def test_receiving_posts_ledger_rows_linked_to_the_document(client, login, db):
    r = receive(client, login(SUP), db, [{"item_id": item_id(db, "PL-001"), "qty": 24, "unit_cost": 2.75},
                                         {"item_id": item_id(db, "BW-001"), "qty": 12, "unit_cost": 2.0}])
    assert r.status_code == 201
    doc = r.json()
    assert doc["status"] == "posted" and doc["invoice_number"] == "INV-1001" and doc["total"] == 24 * 2.75 + 12 * 2.0
    assert doc["supplier"] == "Gulf Catering Supplies" and doc["received_by_name"] == "Sam Supervisor"
    assert balance(db, "PL-001", "MK") == 224 == ledger_sum(db, "PL-001", "MK")
    assert balance(db, "BW-001", "MK") == 102 == ledger_sum(db, "BW-001", "MK")
    txns = db.scalars(select(StockTransaction).where(StockTransaction.ref_type == "receipt")).all()
    assert {t.ref_id for t in txns} == {doc["id"]} and {t.txn_type for t in txns} == {"receipt"}
    assert all("INV-1001" in t.reason for t in txns)
    assert sorted(ln["transaction_id"] for ln in doc["lines"]) == sorted(t.id for t in txns)


def test_invoice_numbers_are_normalised_and_cannot_be_posted_twice_for_a_supplier(client, login, db):
    h = login(SUP)
    assert receive(client, h, db, invoice="  inv  77 ").json()["invoice_number"] == "INV 77"
    dup = receive(client, h, db, invoice="INV 77")
    assert dup.status_code == 409 and "already posted" in dup.json()["detail"]
    assert balance(db, "PL-001", "MK") == 224  # the second attempt changed nothing
    assert receive(client, h, db, invoice="INV 77", supplier="Hotel Ware Trading").status_code == 201


def test_database_refuses_a_second_posted_document_for_the_same_invoice(client, login, db):
    first = receive(client, login(SUP), db, invoice="DB-1").json()
    receipt = db.get(Receipt, first["id"])
    db.add(Receipt(doc_type="receipt", supplier_id=receipt.supplier_id, location_id=receipt.location_id, invoice_number="DB-1",
                   received_by=receipt.received_by, received_at=receipt.received_at, status="posted"))
    with pytest.raises(IntegrityError):
        db.commit()


def test_stewards_cannot_receive_or_see_receiving(client, login, db):
    assert receive(client, login(STEWARD), db, site="MK").status_code == 403
    assert client.get("/api/receipts", headers=login(STEWARD)).status_code == 403
    assert client.get("/api/receipts/1", headers=login(STEWARD)).status_code == 403


def test_receiving_is_location_scoped(client, login, db):
    doc = receive(client, login(SUP), db, invoice="MK-1").json()
    assert receive(client, login(SUP_RB), db, invoice="MK-2", site="MK").status_code == 403
    assert client.get(f"/api/receipts/{doc['id']}", headers=login(SUP_RB)).status_code == 403
    assert client.get("/api/receipts", headers=login(SUP_RB)).json()["total"] == 0
    assert client.get("/api/receipts", headers=login(MGR)).json()["total"] == 1
    assert client.get(f"/api/receipts?location_id={loc_id(db, 'MK')}", headers=login(SUP_RB)).status_code == 403


def test_receiving_validates_input(client, login, db):
    h = login(SUP)
    pl = item_id(db, "PL-001")
    assert receive(client, h, db, lines=[{"item_id": pl, "qty": 0}]).status_code == 422
    assert receive(client, h, db, lines=[{"item_id": pl, "qty": 5, "unit_cost": -1}]).status_code == 422
    assert receive(client, h, db, lines=[{"item_id": 9999, "qty": 5}]).status_code == 400
    assert receive(client, h, db, lines=[{"item_id": pl, "qty": 5}, {"item_id": pl, "qty": 6}]).status_code == 400
    empty = client.post("/api/receipts", headers=h, json={"supplier_id": 1, "location_id": loc_id(db, "MK"),
                                                          "invoice_number": "X", "lines": []})
    assert empty.status_code == 422
    unknown = client.post("/api/receipts", headers=h, json={"supplier_id": 9999, "location_id": loc_id(db, "MK"),
                                                            "invoice_number": "X", "lines": [{"item_id": pl, "qty": 1}]})
    assert unknown.status_code == 400
    blank = client.post("/api/receipts", headers=h, json={"supplier_id": 1, "location_id": loc_id(db, "MK"),
                                                          "invoice_number": "", "lines": [{"item_id": pl, "qty": 1}]})
    assert blank.status_code == 422
    assert balance(db, "PL-001", "MK") == 200


def test_inactive_supplier_or_item_cannot_be_received(client, login, db):
    m = login(MGR)
    sid = suppliers(client)["Hotel Ware Trading"]
    client.put(f"/api/suppliers/{sid}", json={"active": False}, headers=m)
    assert receive(client, login(SUP), db, supplier="Gulf Catering Supplies", invoice="A1").status_code == 201
    retire_item(client, m, db, "PL-002")
    r = receive(client, login(SUP), db, [{"item_id": item_id(db, "PL-002"), "qty": 3}], invoice="A2")
    assert r.status_code == 400 and "inactive" in r.json()["detail"]


def test_the_starting_cost_is_filled_from_the_first_priced_invoice_and_then_left_alone(client, login, db):
    h, m = login(SUP), login(MGR)
    line = [{"item_id": item_id(db, "PL-001"), "qty": 10, "unit_cost": 3.10}]
    receive(client, h, db, line, invoice="C-1")
    assert float(db.scalar(select(InventoryItem.unit_cost).where(InventoryItem.code == "PL-001"))) == 2.50   # already set: kept
    db.execute(update(InventoryItem).where(InventoryItem.code == "PL-001").values(unit_cost=None))
    db.commit()
    receive(client, h, db, line, invoice="C-2")
    db.expire_all()
    assert float(db.scalar(select(InventoryItem.unit_cost).where(InventoryItem.code == "PL-001"))) == 3.10   # blank: filled
    receive(client, h, db, [{**line[0], "unit_cost": 9}], invoice="C-3")
    db.expire_all()
    assert float(db.scalar(select(InventoryItem.unit_cost).where(InventoryItem.code == "PL-001"))) == 3.10   # then not overwritten
    log = db.scalar(select(AuditLog).where(AuditLog.action == "receipt.post", AuditLog.after["invoice"].as_string() == "C-2"))
    assert log.after["cost_updates"] == {"PL-001": {"from": None, "to": "3.100"}}
    assert client.get("/api/inventory/items", headers=m).json()["total_value"] > 0


def test_a_failed_document_posts_nothing_and_the_invoice_can_be_retried(client, login, db):
    h = login(MGR)
    bad = [{"item_id": item_id(db, "PL-001"), "qty": 10}, {"item_id": item_id(db, "PN-001"), "qty": 500}]
    r = receive(client, h, db, bad, invoice="R-1", doc_type="supplier_return", site="BQ")
    assert r.status_code == 409 and "Insufficient" in r.json()["detail"]
    db.expire_all()
    assert balance(db, "PL-001", "BQ") == 150  # the first line was rolled back with the second
    assert db.scalars(select(Receipt)).all() == []
    ok = receive(client, h, db, [{"item_id": item_id(db, "PL-001"), "qty": 10}], invoice="R-1", doc_type="supplier_return", site="BQ")
    assert ok.status_code == 201 and balance(db, "PL-001", "BQ") == 140


def test_supplier_returns_reduce_stock_through_issue_entries(client, login, db):
    doc = receive(client, login(SUP), db, [{"item_id": item_id(db, "PL-001"), "qty": 20, "unit_cost": 2.5}], invoice="CN-5",
                  doc_type="supplier_return").json()
    assert doc["doc_type"] == "supplier_return" and balance(db, "PL-001", "MK") == 180
    txn = db.scalar(select(StockTransaction).where(StockTransaction.ref_id == doc["id"]))
    assert txn.txn_type == "issue" and txn.qty_delta == -20 and "Return to supplier" in txn.reason


def test_void_reverses_stock_with_new_entries_and_frees_the_invoice_number(client, login, db):
    doc = receive(client, login(SUP), db, invoice="V-1").json()
    assert client.post(f"/api/receipts/{doc['id']}/void", json={"reason": "Wrong delivery note"}, headers=login(SUP)).status_code == 403
    assert client.post(f"/api/receipts/{doc['id']}/void", json={"reason": "no"}, headers=login(MGR)).status_code == 422
    before = len(db.scalars(select(StockTransaction)).all())
    voided = client.post(f"/api/receipts/{doc['id']}/void", json={"reason": "Wrong delivery note"}, headers=login(MGR)).json()
    assert voided["status"] == "void" and voided["void_reason"] == "Wrong delivery note"
    db.expire_all()
    assert balance(db, "PL-001", "MK") == 200 == ledger_sum(db, "PL-001", "MK")
    assert len(db.scalars(select(StockTransaction)).all()) == before + 1  # history kept, reversal appended
    reversal = db.scalar(select(StockTransaction).order_by(StockTransaction.id.desc()))
    assert reversal.ref_type == "receipt_void" and reversal.qty_delta == -24 and "Void of goods receipt" in reversal.reason
    assert client.post(f"/api/receipts/{doc['id']}/void", json={"reason": "Wrong delivery note"}, headers=login(MGR)).status_code == 409
    assert receive(client, login(SUP), db, invoice="V-1").status_code == 201
    assert db.scalar(select(AuditLog.id).where(AuditLog.action == "receipt.void"))


def test_voiding_a_return_puts_the_stock_back(client, login, db):
    doc = receive(client, login(MGR), db, [{"item_id": item_id(db, "PL-001"), "qty": 15}], invoice="CN-9", doc_type="supplier_return").json()
    assert balance(db, "PL-001", "MK") == 185
    client.post(f"/api/receipts/{doc['id']}/void", json={"reason": "Credit note cancelled"}, headers=login(MGR))
    assert balance(db, "PL-001", "MK") == 200 == ledger_sum(db, "PL-001", "MK")


def test_list_filters_search_and_detail(client, login, db):
    h = login(SUP)
    a = receive(client, h, db, invoice="ALPHA-1").json()
    receive(client, h, db, invoice="BETA-2", supplier="Hotel Ware Trading", site="BQ")
    m = login(MGR)
    assert client.get("/api/receipts?q=alpha", headers=m).json()["total"] == 1
    assert client.get(f"/api/receipts?supplier_id={suppliers(client)['Hotel Ware Trading']}", headers=m).json()["total"] == 1
    assert client.get(f"/api/receipts?location_id={loc_id(db, 'BQ')}", headers=m).json()["total"] == 1
    client.post(f"/api/receipts/{a['id']}/void", json={"reason": "Entered twice by mistake"}, headers=m)
    assert client.get("/api/receipts?receipt_status=void", headers=m).json()["total"] == 1
    assert client.get("/api/receipts?size=1&page=2", headers=m).json()["items"][0]["invoice_number"] == "ALPHA-1"
    detail = client.get(f"/api/receipts/{a['id']}", headers=m).json()
    assert detail["lines"][0]["name"] == "Dinner Plate 27cm" and client.get("/api/receipts/9999", headers=m).status_code == 404


def test_receipts_appear_in_reports_and_reconciliation(client, login, db, clock):
    receive(client, login(SUP), db, invoice="RPT-1")
    m = login(MGR)
    daily = client.get(f"/api/reports/daily?anchor=2026-03-02&location_id={loc_id(db, 'MK')}", headers=m).json()
    section = next(s for s in daily["sections"] if s["id"] == "inventory")
    assert any("Goods receipt" in (r["reason"] or "") and r["qty"] == 24 for r in section["rows"])
    recon = client.get(f"/api/stock/reconciliation?location_id={loc_id(db, 'MK')}&month=2026-03", headers=m).json()
    row_ = next(r for r in recon["rows"] if r["code"] == "PL-001")
    assert row_["receipts"] == 24 and row_["closing"] == 224


def test_line_and_invoice_discounts_roll_up_to_the_total(client, login, db):
    lines = [{"item_id": item_id(db, "PL-001"), "qty": 10, "unit_cost": 5, "discount_type": "percent", "discount": 10},
             {"item_id": item_id(db, "BW-001"), "qty": 4, "unit_cost": 2.5, "discount_type": "amount", "discount": 1}]
    r = receive(client, login(SUP), db, lines, invoice="DISC-1", discount_type="percent", discount=5)
    assert r.status_code == 201
    doc = r.json()
    assert [ln["line_total"] for ln in doc["lines"]] == [45, 9]  # 50 less 10 percent, 10 less 1
    assert [ln["discount_amount"] for ln in doc["lines"]] == [5, 1]
    assert (doc["subtotal"], doc["line_discount_total"]) == (60, 6)
    assert doc["discount_amount"] == 2.7  # 5 percent of the 54 left after line discounts
    assert doc["total_discount"] == 8.7 and doc["total"] == 51.3


def test_discount_rules_are_enforced(client, login, db):
    h, pl = login(SUP), item_id(db, "PL-001")

    def bad(invoice, line, **doc):
        return receive(client, h, db, [{"item_id": pl, "qty": 2, **line}], invoice=invoice, **doc).status_code

    assert bad("D-1", {"unit_cost": 5, "discount_type": "percent", "discount": 101}) == 400
    assert bad("D-2", {"unit_cost": 5, "discount_type": "amount", "discount": 11}) == 400  # more than the 10 line value
    assert bad("D-3", {"discount_type": "amount", "discount": 1}) == 400  # a discount needs a unit cost
    assert bad("D-4", {"unit_cost": 5}, discount_type="amount", discount=11) == 400  # more than the invoice value
    assert balance(db, "PL-001", "MK") == 200  # nothing was posted
    assert bad("D-5", {"unit_cost": 5, "discount_type": "amount", "discount": 10}) == 201  # a full discount is allowed


def test_the_filled_cost_is_the_net_price_after_the_line_discount(client, login, db):
    db.execute(update(InventoryItem).where(InventoryItem.code == "PL-001").values(unit_cost=None))
    db.commit()
    lines = [{"item_id": item_id(db, "PL-001"), "qty": 10, "unit_cost": 5, "discount_type": "percent", "discount": 20}]
    assert receive(client, login(MGR), db, lines, invoice="NET-1").status_code == 201
    item = client.get("/api/inventory/items?search=dinner", headers=login(MGR)).json()["items"][0]
    assert item["unit_cost"] == 4


def test_item_list_shows_average_cost_and_the_last_purchase_by_invoice_date(client, login, db, clock):
    h, sup = manager_headers(client), login(SUP)
    pl = item_id(db, "PL-001")
    r1 = receive(client, sup, db, [{"item_id": pl, "qty": 10, "unit_cost": 3.0}], invoice="NEW", invoice_date="2026-02-27")
    # entered later but dated earlier, so it is not the last purchase
    r2 = receive(client, sup, db, [{"item_id": pl, "qty": 10, "unit_cost": 9.0}], invoice="OLD", invoice_date="2026-02-01")
    assert r1.status_code == r2.status_code == 201, (r1.json(), r2.json())
    item = next(i for i in client.get("/api/inventory/items?size=200", headers=h).json()["items"] if i["id"] == pl)
    assert item["last_purchase"]["price"] == 3.0 and item["last_purchase"]["supplier"] == "Gulf Catering Supplies"
    assert item["avg_cost"] is not None


def test_stock_movements_from_an_invoice_carry_its_invoice_date(client, login, db, clock):
    h = manager_headers(client)
    receive(client, login(SUP), db, invoice="DATED", invoice_date="2026-02-27")
    receive(client, login(SUP), db, invoice="UNDATED")
    rows = client.get("/api/inventory/transactions?txn_type=receipt", headers=h).json()["items"]
    assert sorted(r["invoice_date"] or "" for r in rows) == ["", "2026-02-27"]


def test_received_on_defaults_to_today_has_no_past_limit_and_cannot_be_in_the_future(client, login, db, clock):
    sup = login(SUP)
    assert receive(client, sup, db, invoice="R-1").json()["received_on"] == "2026-03-02"
    assert receive(client, sup, db, invoice="R-2", received_on="2025-11-05").json()["received_on"] == "2025-11-05"
    future = receive(client, sup, db, invoice="R-3", received_on="2026-03-03")
    assert future.status_code == 400 and "future" in future.json()["detail"]


def test_a_posted_document_can_be_edited_for_its_labels_and_dates_but_not_its_stock(client, login, db, clock):
    sup, mgr = login(SUP), manager_headers(client)
    first = receive(client, sup, db, invoice="E-1", invoice_date="2026-02-20").json()
    receive(client, sup, db, invoice="E-2")
    before = balance(db, "PL-001", "MK")
    assert client.put(f"/api/receipts/{first['id']}", json={"note": "x"}, headers=sup).status_code == 403
    r = client.put(f"/api/receipts/{first['id']}", headers=mgr, json={"invoice_number": " e-9 ", "invoice_date": "2026-02-18",
                                                                     "received_on": "2026-02-21", "note": "Fixed the dates"})
    assert r.status_code == 200
    doc = r.json()
    assert (doc["invoice_number"], doc["invoice_date"], doc["received_on"], doc["note"]) == ("E-9", "2026-02-18", "2026-02-21", "Fixed the dates")
    assert balance(db, "PL-001", "MK") == before and doc["total"] == first["total"]
    assert db.scalar(select(AuditLog.id).where(AuditLog.action == "receipt.edit")) is not None
    assert client.put(f"/api/receipts/{first['id']}", headers=mgr, json={"invoice_number": "E-2"}).status_code == 409
    assert client.put(f"/api/receipts/{first['id']}", headers=mgr, json={"received_on": "2026-03-03"}).status_code == 400
    assert client.put(f"/api/receipts/{first['id']}", headers=mgr, json={"invoice_date": None}).json()["invoice_date"] is None
    client.post(f"/api/receipts/{first['id']}/void", headers=mgr, json={"reason": "Entered twice by mistake"})
    assert client.put(f"/api/receipts/{first['id']}", headers=mgr, json={"note": "again"}).status_code == 409


def test_the_documents_list_can_filter_by_the_invoice_date_or_the_day_received(client, login, db, clock):
    sup, mgr = login(SUP), manager_headers(client)
    receive(client, sup, db, invoice="F-1", invoice_date="2026-02-10", received_on="2026-02-25")
    url = "/api/receipts?date_from=2026-02-20&date_to=2026-02-28"
    assert client.get(url, headers=mgr).json()["total"] == 0
    assert client.get(url + "&date_by=received", headers=mgr).json()["total"] == 1


def test_prices_discounts_and_totals_are_kept_to_a_thousandth(client, login, db, clock):
    doc = receive(client, login(SUP), db, [{"item_id": item_id(db, "PL-001"), "qty": 10, "unit_cost": 29.745, "discount_type": "percent", "discount": 3}],
                  invoice="THOU-1").json()
    line = doc["lines"][0]
    assert line["unit_cost"] == 29.745 and line["gross"] == 297.45
    assert line["discount_amount"] == 8.924 and line["line_total"] == 288.526  # 3 percent of 297.450, kept to three places
    assert doc["subtotal"] == 297.45 and doc["total"] == 288.526


def test_the_migration_fills_blank_starting_costs_from_the_latest_priced_invoice(client, login, db):
    import importlib.util, pathlib
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    pl, pn = item_id(db, "PL-001"), item_id(db, "PN-001")
    receive(client, login(MGR), db, [{"item_id": pl, "qty": 10, "unit_cost": 3.0}], invoice="M-1", invoice_date="2026-01-10")
    receive(client, login(MGR), db, [{"item_id": pl, "qty": 10, "unit_cost": 4.0, "discount_type": "percent", "discount": 25}], invoice="M-2", invoice_date="2026-02-10")
    db.execute(update(InventoryItem).where(InventoryItem.id.in_([pl, pn])).values(unit_cost=None))
    db.commit()
    path = pathlib.Path(__file__).parent.parent / "alembic" / "versions" / "n8b2d6f0c4e7_fill_blank_start_costs.py"
    spec = importlib.util.spec_from_file_location("fill", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    connection = db.connection()
    with Operations.context(MigrationContext.configure(connection)):
        module.upgrade()
    db.expire_all()
    assert float(db.get(InventoryItem, pl).unit_cost) == 3.0       # newest invoice 4.00 less 25%
    assert db.get(InventoryItem, pn).unit_cost is None              # never bought: stays blank


def test_the_stock_chart_puts_a_late_entered_invoice_on_its_invoice_date_or_received_date(client, login, db, clock):
    clock.set(2026, 3, 20, 9, 0)                                                        # entered on 20 March
    m = login(MGR)
    r = receive(client, m, db, [{"item_id": item_id(db, "PL-001"), "qty": 40, "unit_cost": 2.0}], invoice="LATE-1",
                invoice_date="2026-03-02", received_on="2026-03-03")
    assert r.status_code == 201
    mk = loc_id(db, "MK")

    def moved(by, day_from, day_to):
        data = client.get(f"/api/stock/insights?location_id={mk}&date_from={day_from}&date_to={day_to}&date_by={by}", headers=m).json()
        return {p["date"]: p["in"] for p in data["movement"] if p["in"]}

    assert moved("invoice", "2026-03-01", "2026-03-05") == {"2026-03-02": 40}
    assert moved("received", "2026-03-01", "2026-03-05") == {"2026-03-03": 40}
    assert moved("invoice", "2026-03-18", "2026-03-22") == {}                          # not on the day it was typed in
    spend = client.get(f"/api/stock/analysis?location_id={mk}&date_from=2026-03-01&date_to=2026-03-05", headers=m).json()
    assert spend["total_spend"] == 80.0 and spend["spend_by_supplier"][0]["value"] == 80.0
    assert [p["period"] for p in spend["spend_trend"] if p["spend"]] == ["2026-03-02"]


def test_price_history_lists_each_invoice_price_with_the_change_and_a_summary(client, login, db, clock):
    m, sup = login(MGR), login(SUP)
    pl = item_id(db, "PL-001")
    receive(client, m, db, [{"item_id": pl, "qty": 10, "unit_cost": 2.0}], invoice="P-1", invoice_date="2026-01-10")
    receive(client, m, db, [{"item_id": pl, "qty": 30, "unit_cost": 5.0, "discount_type": "percent", "discount": 20}], invoice="P-2", invoice_date="2026-02-10")
    receive(client, m, db, [{"item_id": pl, "qty": 10, "unit_cost": 1.5}], invoice="P-0", invoice_date="2025-12-01")   # entered last, dated first
    data = client.get(f"/api/inventory/items/{pl}/price-history", headers=m).json()
    assert [(p["invoice"], p["price"]) for p in data["points"]] == [("P-0", 1.5), ("P-1", 2.0), ("P-2", 4.0)]
    assert [p["change_pct"] for p in data["points"]] == [None, 33.3, 100.0]
    s = data["summary"]
    assert (s["first"], s["latest"], s["lowest"], s["highest"], s["count"], s["change_pct"]) == (1.5, 4.0, 1.5, 4.0, 3, 166.7)
    assert s["average"] == round((1.5 * 10 + 2.0 * 10 + 4.0 * 30) / 50, 3)
    assert client.get(f"/api/inventory/items/{pl}/price-history", headers=sup).status_code == 200      # supervisors post receipts
    assert client.get("/api/inventory/items/9999/price-history", headers=m).status_code == 404
    assert client.get(f"/api/inventory/items/{pl}/price-history", headers=login("steward.mk@example.test")).status_code == 403   # prices are not for stewards
    assert client.get(f"/api/inventory/items/{item_id(db, 'PN-001')}/price-history", headers=m).json()["summary"] is None


def test_a_posted_invoice_can_have_its_lines_corrected_all_or_nothing(client, login, db, clock):
    m, sup = login(MGR), login(SUP)
    pl, pn = item_id(db, "PL-001"), item_id(db, "PN-001")
    start = balance(db, "PL-001", "MK")
    first = receive(client, m, db, [{"item_id": pl, "qty": 24, "unit_cost": 2.75}], invoice="FIX-1", invoice_date="2026-02-20").json()
    assert balance(db, "PL-001", "MK") == start + 24
    body = {"supplier_id": first["supplier_id"], "location_id": first["location_id"], "invoice_number": "FIX-1", "invoice_date": "2026-02-20",
            "lines": [{"item_id": pl, "qty": 20, "unit_cost": 3.0}, {"item_id": pn, "qty": 6, "unit_cost": 1.5}], "reason": "Quantity and price were mistyped"}
    url = f"/api/receipts/{first['id']}/correct"
    assert client.post(url, json=body, headers=sup).status_code == 403                                  # needs the right to void
    made = client.post(url, json=body, headers=m)
    assert made.status_code == 201, made.text
    new = made.json()
    assert new["invoice_number"] == "FIX-1" and new["total"] == 69.0 and new["status"] == "posted" and len(new["lines"]) == 2
    db.expire_all()
    assert balance(db, "PL-001", "MK") == start + 20                                                    # the old 24 reversed, the right 20 posted
    old = client.get(f"/api/receipts/{first['id']}", headers=m).json()
    assert old["status"] == "void" and f"#{new['id']}" in old["void_reason"]
    posted = [r for r in client.get("/api/receipts?size=50", headers=m).json()["items"] if r["invoice_number"] == "FIX-1" and r["status"] == "posted"]
    assert [r["id"] for r in posted] == [new["id"]]                                                     # one live document for the invoice
    # a correction that cannot be posted changes nothing
    bad = {**body, "lines": [{"item_id": 99999, "qty": 1, "unit_cost": 1}], "reason": "This should fail whole"}
    assert client.post(f"/api/receipts/{new['id']}/correct", json=bad, headers=m).status_code == 400
    db.expire_all()
    assert balance(db, "PL-001", "MK") == start + 20
    assert client.get(f"/api/receipts/{new['id']}", headers=m).json()["status"] == "posted"
    # nor can it take another invoice's number
    receive(client, m, db, [{"item_id": pl, "qty": 1, "unit_cost": 1}], invoice="OTHER-1")
    clash = {**body, "invoice_number": "OTHER-1", "reason": "Wrong number on purpose"}
    assert client.post(f"/api/receipts/{new['id']}/correct", json=clash, headers=m).status_code == 409
    assert client.get(f"/api/receipts/{new['id']}", headers=m).json()["status"] == "posted"


def test_an_item_can_have_a_preferred_supplier_and_others_and_learns_new_ones_from_invoices(client, login, db, clock):
    m = login(MGR)
    ids = suppliers(client)
    names = list(ids)
    assert len(names) >= 2
    a, b = ids[names[0]], ids[names[1]]
    pl = item_id(db, "PL-001")
    shown = client.put(f"/api/inventory/items/{pl}", json={"supplier_id": a, "supplier_ids": [b, a]}, headers=m).json()      # the preferred one is not repeated
    assert shown["supplier_id"] == a and shown["supplier_ids"] == [b] and shown["other_suppliers"] == [names[1]]
    assert client.put(f"/api/inventory/items/{pl}", json={"supplier_ids": [99999]}, headers=m).status_code == 400
    assert client.put(f"/api/inventory/items/{pl}", json={"supplier_ids": []}, headers=m).json()["supplier_ids"] == []
    # buying from a supplier not yet listed adds them
    receive(client, m, db, [{"item_id": pl, "qty": 5, "unit_cost": 2.0}], invoice="SUP-B", supplier=names[1])
    again = [i for i in client.get("/api/inventory/items?size=200", headers=m).json()["items"] if i["id"] == pl][0]
    assert again["supplier_ids"] == [b]
    # buying from the preferred supplier does not list them twice
    receive(client, m, db, [{"item_id": pl, "qty": 5, "unit_cost": 2.0}], invoice="SUP-A", supplier=names[0])
    assert [i for i in client.get("/api/inventory/items?size=200", headers=m).json()["items"] if i["id"] == pl][0]["supplier_ids"] == [b]


def test_cost_consumed_ignores_supplier_returns_and_voided_invoices_but_counts_real_use(client, login, db, clock):
    m = login(MGR)
    mk = loc_id(db, "MK")
    pl = item_id(db, "PL-001")

    def report():
        return client.get(f"/api/stock/cost-report?date_from=2026-03-01&date_to=2026-03-31&location_id={mk}", headers=m).json()["totals"]

    bought = receive(client, m, db, [{"item_id": pl, "qty": 10, "unit_cost": 2.0}], invoice="CC-1").json()
    assert report()["cost_consumed"] == 0
    receive(client, m, db, [{"item_id": pl, "qty": 2, "unit_cost": 2.0}], invoice="CC-R", doc_type="supplier_return")
    assert report()["cost_consumed"] == 0                                                               # sent back, not used
    assert report()["returns"] < 0
    assert client.post(f"/api/receipts/{bought['id']}/void", json={"reason": "wrong invoice"}, headers=m).status_code == 200
    after_void = report()
    assert after_void["cost_consumed"] == 0 and after_void["purchases"] == 0                            # the void took its own purchase out
    assert client.post("/api/inventory/transactions", json={"item_id": pl, "location_id": mk, "txn_type": "issue", "qty": 3, "reason": "used"}, headers=m).status_code == 201
    assert report()["cost_consumed"] > 0 and report()["issued"] == report()["cost_consumed"]            # real use still counts


def test_the_price_shown_includes_the_invoice_discount_and_the_spend_charts_agree(client, login, db, clock):
    m = login(MGR)
    kn = item_id(db, "KN-001")
    receive(client, m, db, [{"item_id": kn, "qty": 4, "unit_cost": 10.0, "discount_type": "percent", "discount": 10}], invoice="DD-1",
            discount_type="amount", discount=2)                                    # 4 x 10, less 10% = 36, less 2 off the invoice = 34, so 8.5 each
    point = client.get(f"/api/inventory/items/{kn}/price-history", headers=m).json()["points"][0]
    assert point["price"] == 8.5
    listed = [i for i in client.get("/api/inventory/items?size=200", headers=m).json()["items"] if i["id"] == kn][0]
    assert listed["last_purchase"]["price"] == 8.5
    an = client.get("/api/stock/analysis?date_from=2026-03-01&date_to=2026-03-31", headers=m).json()
    assert round(sum(x["value"] for x in an["spend_by_supplier"]), 2) == round(sum(x["value"] for x in an["spend_by_category"]), 2) == 34.0


def test_a_locked_month_cannot_be_changed_by_posting_editing_voiding_or_a_catch_up(client, login, db, clock):
    m = login(MGR)
    pl = item_id(db, "PL-001")
    first = receive(client, m, db, [{"item_id": pl, "qty": 5, "unit_cost": 2.0}], invoice="LK-1", invoice_date="2026-01-20").json()
    assert client.put("/api/settings", json={"values": {"stock.lock_through": 202601}}, headers=m).status_code == 200
    late = receive(client, m, db, [{"item_id": pl, "qty": 5, "unit_cost": 2.0}], invoice="LK-2", invoice_date="2026-01-25")
    assert late.status_code == 409 and "locked" in late.json()["detail"]                                # nothing new can land in January
    assert client.post(f"/api/receipts/{first['id']}/void", json={"reason": "was a mistake"}, headers=m).status_code == 409
    assert client.put(f"/api/receipts/{first['id']}", json={"invoice_date": "2026-02-02"}, headers=m).status_code == 409   # nor leave it
    ok = receive(client, m, db, [{"item_id": pl, "qty": 5, "unit_cost": 2.0}], invoice="LK-3", invoice_date="2026-02-03")
    assert ok.status_code == 201                                                                         # February is open
    client.put("/api/settings", json={"values": {"stock.lock_through": 0}}, headers=m)
    assert client.post(f"/api/receipts/{first['id']}/void", json={"reason": "was a mistake"}, headers=m).status_code == 200   # unlocked again


def test_missing_and_written_off_stock_is_shown_apart_from_breakage_and_dated_when_reported(client, login, db, clock):
    m = login(MGR)
    mk, pl = loc_id(db, "MK"), item_id(db, "PL-001")

    def report():
        return client.get(f"/api/stock/cost-report?date_from=2026-03-01&date_to=2026-03-31&location_id={mk}", headers=m).json()["totals"]

    for kind, qty in (("breakage", 2), ("missing", 3)):
        made = client.post("/api/breakage", json={"location_id": mk, "item_id": pl, "qty": qty, "incident_type": kind, "reason": "test"}, headers=login("steward.mk@example.test"))
        assert made.status_code == 201, made.text
        done = client.post(f"/api/breakage/{made.json()['id']}/review", json={"qty": qty, "reason": "ok", "preventive_action": "none"}, headers=login("sup.mk@example.test"))
        if done.json()["status"] == "pending_approval":
            assert client.post(f"/api/breakage/{made.json()['id']}/approve", json={"note": "ok"}, headers=m).status_code == 200
    totals = report()
    assert totals["breakage_damage"] > 0 and totals["missing_written_off"] > 0
    assert round(totals["cost_consumed"], 3) == round(totals["breakage_damage"] + totals["missing_written_off"], 3)
