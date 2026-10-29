from sqlalchemy import select

from app.models import AuditLog, InventoryBalance, InventoryItem, Notification

from .helpers import MGR, SUP, item_id, loc_id
from .test_stock import count


def post_manual(client, h, db, txn_type, qty, reason="Stock found in the store room", code="PL-001"):
    return client.post("/api/inventory/transactions", headers=h, json={"item_id": item_id(db, code), "location_id": loc_id(db, "MK"), "txn_type": txn_type, "qty": qty, "reason": reason})


def test_a_count_above_everything_received_is_refused_and_everyone_is_told(client, login, db, clock):
    sup, m = login(SUP), login(MGR)
    refused = count(client, sup, db, 500)
    assert refused.status_code == 400
    assert "more than the 200 received" in refused.json()["detail"] and "opening stock 200" in refused.json()["detail"]
    alert = db.scalars(select(Notification).where(Notification.kind == "count_over_received")).first()
    assert alert and alert.priority == "critical" and alert.requires_ack and "counted 500, received 200" in alert.title
    assert {n.user_id for n in db.scalars(select(Notification).where(Notification.kind == "count_over_received"))} >= {1}
    assert db.scalar(select(AuditLog).where(AuditLog.action == "stock.count_blocked")) is not None
    assert any(n["kind"] == "count_over_received" for n in client.get("/api/notifications", headers=m).json()["items"])


def test_manual_increases_and_returns_do_not_raise_what_a_count_may_reach(client, login, db, clock):
    sup, m = login(SUP), login(MGR)
    assert post_manual(client, m, db, "adjustment", 50).status_code == 201     # a manager adds 50 by hand
    assert post_manual(client, sup, db, "receipt", 30, reason=None).status_code == 201  # a receipt with no invoice
    assert count(client, sup, db, 250, reason="Found extra stock").status_code == 400
    assert count(client, sup, db, 200).status_code == 201


def test_a_manager_can_add_opening_stock_when_there_is_no_invoice(client, login, db, clock):
    sup, m = login(SUP), login(MGR)
    assert post_manual(client, sup, db, "opening", 50).status_code == 403     # only a manager
    assert post_manual(client, m, db, "opening", 50, reason="x").status_code == 400   # a reason is needed
    assert post_manual(client, m, db, "opening", 50).status_code == 409      # PL-001 already has opening stock here
    pl = db.scalar(select(InventoryItem).where(InventoryItem.code == "PL-001"))
    made = client.post("/api/inventory/items", headers=m, json={"name": "Opening Test Tray", "category_id": pl.category_id, "unit_id": pl.unit_id}).json()["code"]
    assert post_manual(client, m, db, "opening", 50, code=made).status_code == 201
    assert post_manual(client, m, db, "opening", 50, code=made).status_code == 409      # opening stock is recorded once
    assert count(client, sup, db, 50, code=made).status_code == 201


def test_a_count_above_the_system_quantity_needs_a_reason_and_is_flagged(client, login, db, clock):
    sup = login(SUP)
    client.post("/api/inventory/transactions", headers=sup, json={"item_id": item_id(db, "PL-001"), "location_id": loc_id(db, "MK"), "txn_type": "issue", "qty": 50})
    without = count(client, sup, db, 180)
    assert without.status_code == 400 and "Give a reason" in without.json()["detail"]
    made = count(client, sup, db, 180, reason="Two issues were posted twice")
    assert made.status_code == 201
    flag = db.scalars(select(Notification).where(Notification.kind == "count_surplus")).first()
    assert flag and "counted 180, system 150" in flag.title and flag.requires_ack
    assert count(client, sup, db, 150).status_code == 201                   # equal to the system needs no reason


def test_posting_checks_the_limit_again(client, login, db, clock):
    sup, m = login(SUP), login(MGR)
    supplier = client.get("/api/suppliers", headers=m).json()[0]["id"]
    receipt = {"supplier_id": supplier, "location_id": loc_id(db, "MK"), "invoice_number": "PST-1", "lines": [{"item_id": item_id(db, "PL-001"), "qty": 10}]}
    posted = client.post("/api/receipts", json=receipt, headers=m).json()
    made = count(client, sup, db, 210)                                       # 200 opening + 10 invoiced, equal to the system
    assert made.status_code == 201
    assert client.post(f"/api/receipts/{posted['id']}/void", headers=m, json={"reason": "Entered by mistake"}).status_code == 200
    again = client.post(f"/api/stock/counts/{made.json()['id']}/post", headers=m)
    assert again.status_code == 409 and "recount" in again.json()["detail"]


def test_the_count_limits_endpoint_shows_how_received_is_made_up(client, login, db, clock):
    sup, m = login(SUP), login(MGR)
    client.post("/api/receipts", headers=m, json={"supplier_id": client.get("/api/suppliers", headers=m).json()[0]["id"], "location_id": loc_id(db, "MK"),
                                                  "invoice_number": "LIM-1", "lines": [{"item_id": item_id(db, "PL-001"), "qty": 10}]})
    rows = client.get(f"/api/stock/count-limits?location_id={loc_id(db, 'MK')}", headers=sup).json()
    plate = next(r for r in rows if r["item_id"] == item_id(db, "PL-001"))
    assert plate == {"item_id": plate["item_id"], "received": 210, "system_qty": 210, "invoices": 10, "opening": 200, "transfers_in": 0}
    assert client.get(f"/api/stock/count-limits?location_id={loc_id(db, 'RB')}", headers=sup).status_code == 403


def test_a_transfer_shows_value_per_line_and_alerts_when_it_asks_for_too_much(client, login, db, clock):
    sup, m = login(SUP), login(MGR)
    mk, bq, plate = loc_id(db, "MK"), loc_id(db, "BQ"), item_id(db, "PL-001")
    stock = {r["item_id"]: r for r in client.get(f"/api/stock/location-stock?location_id={mk}", headers=sup).json()}
    assert stock[plate]["qty"] == 200 and stock[plate]["avg_cost"] == 2.5
    too_many = client.post("/api/stock/transfers", headers=sup, json={"from_location_id": mk, "to_location_id": bq, "lines": [{"item_id": plate, "qty": 500}]})
    assert too_many.status_code == 409 and "500 were asked for" in too_many.json()["detail"]
    assert db.scalar(select(Notification).where(Notification.kind == "transfer_over_stock")) is not None
    assert db.scalar(select(AuditLog).where(AuditLog.action == "stock.transfer_blocked")) is not None
    made = client.post("/api/stock/transfers", headers=sup, json={"from_location_id": mk, "to_location_id": bq, "lines": [{"item_id": plate, "qty": 4}, {"item_id": item_id(db, "PL-002"), "qty": 10}]}).json()
    assert [l["value"] for l in made["lines"]] == [10.0, 16.0] and made["total_value"] == 26.0       # 4 x 2.50 and 10 x 1.60
    client.post(f"/api/stock/transfers/{made['id']}/decision", headers=m, json={"approve": True})
    done = next(t for t in client.get("/api/stock/transfers", headers=m).json() if t["id"] == made["id"])
    assert done["total_value"] == 26.0 and done["status"] == "completed"


def test_breakage_for_several_items_is_valued_at_average_cost_with_a_total(client, login, db, clock):
    steward, sup, m = login("steward.mk@example.test"), login(SUP), login(MGR)
    mk = loc_id(db, "MK")
    body = {"location_id": mk, "incident_type": "breakage", "reason": "Tray dropped",
            "lines": [{"item_id": item_id(db, "PL-001"), "qty": 2}, {"item_id": item_id(db, "PL-002"), "qty": 3}]}
    hidden = client.post("/api/breakage/batch", json=body, headers=steward).json()
    assert len(hidden["incidents"]) == 2 and hidden["total_cost"] is None and all(i["est_cost"] is None for i in hidden["incidents"])
    shown = client.post("/api/breakage/batch", json=body, headers=sup).json()
    assert [i["est_cost"] for i in shown["incidents"]] == [5.0, 4.8] and shown["total_cost"] == 9.8     # 2 x 2.50 and 3 x 1.60
    assert client.post("/api/breakage/batch", json={**body, "lines": [body["lines"][0], body["lines"][0]]}, headers=sup).status_code == 400
    assert client.post("/api/breakage/batch", json={**body, "lines": []}, headers=sup).status_code == 422
    listing = client.get(f"/api/breakage?location_id={mk}", headers=m).json()
    assert listing["total"] == 4 and listing["totals"] == {"cost": 19.6, "units": 10}
    rejected = shown["incidents"][0]["id"]
    client.post(f"/api/breakage/{rejected}/reject", json={"reason": "Counted twice by mistake"}, headers=m)
    assert client.get(f"/api/breakage?location_id={mk}", headers=m).json()["totals"] == {"cost": 14.6, "units": 8}


def test_all_locations_adds_up_without_changing_anything(client, login, db, clock):
    m, sup = login(MGR), login(SUP)
    one = {l: client.get(f"/api/stock/reconciliation?location_id={loc_id(db, l)}&month=2026-03", headers=m).json() for l in ("MK", "BQ", "RB")}
    everything = client.get("/api/stock/reconciliation?month=2026-03", headers=m).json()
    assert [s["location"] for s in everything["locations"]] == sorted(s["location"] for s in everything["locations"])
    assert everything["total_closing"] == sum(o["total_closing"] for o in one.values())
    assert everything["closing_value"] == round(sum(sum(r["closing_value"] for r in o["rows"]) for o in one.values()), 2)
    mine = client.get("/api/stock/reconciliation?month=2026-03", headers=sup).json()      # a supervisor's "all" is only their locations
    assert {s["location"] for s in mine["locations"]} == {"Main Kitchen", "Banquet Hall"}
    balances_before = db.scalars(select(InventoryBalance)).all()
    assert len(balances_before) == len(db.scalars(select(InventoryBalance)).all())
    costs = client.get("/api/stock/cost-report?date_from=2026-03-01&date_to=2026-03-31", headers=m).json()
    assert len(costs["locations"]) == 3 and costs["totals"]["closing_value"] == round(sum(p["totals"].get("closing_value", 0) for p in costs["locations"]), 2)
    assert client.get("/api/stock/cost-report?date_from=2026-03-01&date_to=2026-03-31", headers=login("steward.mk@example.test")).status_code == 403


def test_a_transfer_between_locations_is_not_counted_as_stock_in_or_out_across_all_locations(client, login, db, clock):
    sup, m = login(SUP), login(MGR)
    plate = item_id(db, "PL-001")
    made = client.post("/api/stock/transfers", headers=sup, json={"from_location_id": loc_id(db, "MK"), "to_location_id": loc_id(db, "BQ"), "lines": [{"item_id": plate, "qty": 7}]}).json()
    client.post(f"/api/stock/transfers/{made['id']}/decision", headers=m, json={"approve": True})
    both = client.get("/api/stock/insights?date_from=2026-03-01&date_to=2026-03-02", headers=m).json()
    single = client.get(f"/api/stock/insights?location_id={loc_id(db, 'MK')}&date_from=2026-03-01&date_to=2026-03-02", headers=m).json()
    assert both["totals"]["out"] == 0 and single["totals"]["out"] == 7


def test_the_listed_stock_value_follows_the_chosen_location(client, login, db, clock):
    m = login(MGR)
    whole = client.get("/api/inventory/items", headers=m).json()["total_value"]
    kitchen = client.get(f"/api/inventory/items?location_id={loc_id(db, 'MK')}", headers=m).json()["total_value"]
    assert 0 < kitchen < whole
