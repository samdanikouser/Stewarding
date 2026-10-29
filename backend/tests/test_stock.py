from datetime import timedelta

from sqlalchemy import select

from app.models import ApprovalRecord, Notification, StockTransaction

from .helpers import MGR, STEWARD, SUP, SUP_RB, balance, item_id, ledger_sum, loc_id


def transfer(client, h, db, qty=10, code="PL-001", src="MK", dst="BQ"):
    body = {"from_location_id": loc_id(db, src), "to_location_id": loc_id(db, dst),
            "lines": [{"item_id": item_id(db, code), "qty": qty}], "note": "Banquet setup"}
    return client.post("/api/stock/transfers", json=body, headers=h)


def decide(client, h, transfer_id, approve=True):
    return client.post(f"/api/stock/transfers/{transfer_id}/decision", json={"approve": approve, "note": "ok"}, headers=h)


def test_supervisor_request_waits_for_manager_and_moves_nothing(client, login, db):
    r = transfer(client, login(SUP), db)
    assert r.status_code == 201 and r.json()["status"] == "requested"
    assert balance(db, "PL-001", "MK") == 200 and balance(db, "PL-001", "BQ") == 150
    assert db.scalar(select(Notification.id).where(Notification.kind == "transfer_pending"))


def test_approval_posts_both_sides_atomically_and_only_once(client, login, db):
    t = transfer(client, login(SUP), db).json()
    assert decide(client, login(SUP), t["id"]).status_code == 403
    assert decide(client, login(MGR), t["id"]).json()["status"] == "completed"
    assert balance(db, "PL-001", "MK") == 190 and balance(db, "PL-001", "BQ") == 160
    kinds = {x.txn_type: x.ref_id for x in db.scalars(select(StockTransaction).where(StockTransaction.ref_type == "transfer"))}
    assert kinds == {"transfer_out": t["id"], "transfer_in": t["id"]}
    assert decide(client, login(MGR), t["id"]).status_code == 409
    assert balance(db, "PL-001", "MK") == ledger_sum(db, "PL-001", "MK") == 190
    assert db.scalar(select(ApprovalRecord.id).where(ApprovalRecord.subject_type == "transfer"))


def test_transfer_larger_than_stock_is_refused_when_requested(client, login, db):
    assert transfer(client, login(SUP), db, qty=500).status_code == 409
    assert client.get("/api/stock/transfers", headers=login(MGR)).json() == []
    assert balance(db, "PL-001", "MK") == 200 and balance(db, "PL-001", "BQ") == 150


def test_stock_used_before_approval_blocks_the_transfer(client, login, db):
    t = transfer(client, login(SUP), db, qty=150).json()
    client.post("/api/inventory/transactions", json={"item_id": item_id(db, "PL-001"), "location_id": loc_id(db, "MK"),
                                                    "txn_type": "issue", "qty": 100}, headers=login(SUP))
    assert decide(client, login(MGR), t["id"]).status_code == 409
    listing = client.get("/api/stock/transfers?transfer_status=requested", headers=login(MGR)).json()
    assert [x["id"] for x in listing] == [t["id"]]
    assert balance(db, "PL-001", "MK") == 100 and balance(db, "PL-001", "BQ") == 150


def test_rejected_transfer_changes_no_stock(client, login, db):
    t = transfer(client, login(SUP), db).json()
    assert decide(client, login(MGR), t["id"], approve=False).json()["status"] == "rejected"
    assert balance(db, "PL-001", "MK") == 200
    assert db.scalar(select(Notification.id).where(Notification.kind == "transfer_rejected"))


def test_transfer_scope_rules(client, login, db):
    assert transfer(client, login(SUP_RB), db).status_code == 403   # RB supervisor cannot send from MK
    assert transfer(client, login(STEWARD), db).status_code == 403
    assert transfer(client, login(SUP), db, src="MK", dst="MK").status_code == 400
    assert transfer(client, login(SUP), db, dst="BQ", qty=-1).status_code == 422


def test_manager_requested_transfer_executes_immediately(client, login, db):
    r = transfer(client, login(MGR), db, qty=20)
    assert r.json()["status"] == "completed"
    assert balance(db, "PL-001", "MK") == 180 and balance(db, "PL-001", "BQ") == 170


def test_supervisor_sees_transfers_touching_their_locations_only(client, login, db):
    transfer(client, login(MGR), db, qty=5, src="BQ", dst="RB")
    assert len(client.get("/api/stock/transfers", headers=login(SUP_RB)).json()) == 1
    assert len(client.get("/api/stock/transfers", headers=login(SUP)).json()) == 1  # BQ is theirs


def count(client, h, db, counted, code="PL-001", loc="MK", reason=None):
    body = {"location_id": loc_id(db, loc), "lines": [{"item_id": item_id(db, code), "counted_qty": counted, **({"reason": reason} if reason else {})}]}
    return client.post("/api/stock/counts", json=body, headers=h)


def test_count_with_variance_needs_manager_and_posts_one_adjustment(client, login, db):
    c = count(client, login(SUP), db, 190).json()
    assert c["lines"][0]["system_qty"] == 200 and c["lines"][0]["variance"] == -10
    assert client.post(f"/api/stock/counts/{c['id']}/post", headers=login(SUP)).status_code == 403
    assert balance(db, "PL-001", "MK") == 200
    posted = client.post(f"/api/stock/counts/{c['id']}/post", headers=login(MGR)).json()
    assert posted["status"] == "posted" and posted["lines"][0]["adjustment_txn_id"]
    assert balance(db, "PL-001", "MK") == 190 == ledger_sum(db, "PL-001", "MK")
    assert client.post(f"/api/stock/counts/{c['id']}/post", headers=login(MGR)).status_code == 409


def test_count_without_variance_can_be_posted_by_supervisor(client, login, db):
    c = count(client, login(SUP), db, 200).json()
    assert client.post(f"/api/stock/counts/{c['id']}/post", headers=login(SUP)).json()["status"] == "posted"
    assert db.scalars(select(StockTransaction).where(StockTransaction.ref_type == "count")).all() == []


def test_count_validation_and_scope(client, login, db):
    assert count(client, login(STEWARD), db, 5).status_code == 403
    assert count(client, login(SUP_RB), db, 5).status_code == 403
    assert count(client, login(SUP), db, -1).status_code == 422
    dup = {"location_id": loc_id(db, "MK"), "lines": [{"item_id": item_id(db, "PL-001"), "counted_qty": 1}] * 2}
    assert client.post("/api/stock/counts", json=dup, headers=login(SUP)).status_code == 400


def test_monthly_reconciliation_adds_up_and_carries_forward(client, login, db, clock):
    h, m = login(SUP), login(MGR)
    base = {"item_id": item_id(db, "PL-001"), "location_id": loc_id(db, "MK")}
    clock.advance(hours=1)
    client.post("/api/inventory/transactions", json={**base, "txn_type": "receipt", "qty": 30}, headers=h)
    client.post("/api/inventory/transactions", json={**base, "txn_type": "issue", "qty": 20}, headers=h)
    client.post("/api/inventory/transactions", json={**base, "txn_type": "damage", "qty": 4, "reason": "Dropped tray"}, headers=h)
    c = count(client, h, db, 200).json()  # system is 206
    client.post(f"/api/stock/counts/{c['id']}/post", headers=m)
    url = f"/api/stock/reconciliation?location_id={loc_id(db, 'MK')}&month=2026-03"
    row_ = next(r for r in client.get(url, headers=h).json()["rows"] if r["code"] == "PL-001")
    assert (row_["opening_stock"], row_["receipts"], row_["issues"], row_["breakage_damage"], row_["adjustments"]) == (200, 30, -20, -4, -6)
    assert row_["closing"] == 200 == balance(db, "PL-001", "MK")
    assert row_["counted_qty"] == 200 and row_["count_variance"] == -6
    clock.advance(days=40)
    april = next(r for r in client.get(url.replace("2026-03", "2026-04"), headers=h).json()["rows"] if r["code"] == "PL-001")
    assert april["opening"] == 200 and april["closing"] == 200


def test_reconciliation_validation_and_scope(client, login, db):
    base = f"/api/stock/reconciliation?location_id={loc_id(db, 'MK')}"
    assert client.get(base + "&month=2026-13", headers=login(MGR)).status_code == 400
    assert client.get(base + "&month=2026-03", headers=login(SUP_RB)).status_code == 403
    assert client.get(base + "&month=2026-03", headers=login(STEWARD)).status_code == 403


def test_a_count_cannot_exceed_what_was_received_into_the_location(client, login, db):
    h = login(SUP)
    over = count(client, h, db, 201)  # 200 plates were received into Main Kitchen
    assert over.status_code == 400 and "counted 201 is more than the 200 received" in over.json()["detail"]
    assert client.get(f"/api/stock/counts?location_id={loc_id(db, 'MK')}", headers=h).json() == []  # nothing was saved
    assert count(client, h, db, 200).status_code == 201
    assert count(client, h, db, 150).status_code == 201  # counting fewer is a normal shortage
    never = count(client, h, db, 1, code="PN-001", loc="MK")  # 6 pots were received here
    assert never.status_code == 201
    assert count(client, login(MGR), db, 1, code="PN-001", loc="RB").status_code == 400  # none ever reached the rooftop bar


def test_the_count_limit_follows_receipts_and_transfers_in(client, login, db):
    m, h = login(MGR), login(SUP)
    supplier = client.get("/api/suppliers", headers=m).json()[0]["id"]
    receipt = {"supplier_id": supplier, "location_id": loc_id(db, "MK"), "invoice_number": "CNT-1",
               "lines": [{"item_id": item_id(db, "PL-001"), "qty": 10}]}
    assert count(client, h, db, 205).status_code == 400
    assert client.post("/api/receipts", json=receipt, headers=m).status_code == 201
    assert count(client, h, db, 205).status_code == 201  # 200 opening + 10 received
    client.post("/api/inventory/transactions", headers=h, json={"item_id": item_id(db, "PL-001"), "location_id": loc_id(db, "MK"),
                                                                "txn_type": "issue", "qty": 50})
    assert count(client, h, db, 210).status_code == 400  # above the 160 the system holds: needs a reason
    assert count(client, h, db, 210, reason="An issue was posted twice").status_code == 201  # issuing stock does not lower what was received
    assert count(client, h, db, 211).status_code == 400
    transfer(client, m, db, qty=20, src="MK", dst="BQ")  # BQ received 150 + 20
    assert count(client, h, db, 170, loc="BQ").status_code == 201
    assert count(client, h, db, 171, loc="BQ").status_code == 400


def test_insights_summarise_movements_breakage_and_transfers(client, login, db, clock):
    h, m = login(SUP), login(MGR)
    base = {"item_id": item_id(db, "PL-001"), "location_id": loc_id(db, "MK")}
    client.post("/api/inventory/transactions", json={**base, "txn_type": "receipt", "qty": 30}, headers=h)
    client.post("/api/inventory/transactions", json={**base, "txn_type": "issue", "qty": 8}, headers=h)
    client.post("/api/breakage", headers=h, json={**base, "qty": 2, "incident_type": "breakage", "reason": "Dropped while carrying"})
    transfer(client, m, db, qty=5)
    data = client.get(f"/api/stock/insights?location_id={loc_id(db, 'MK')}&date_from=2026-03-01&date_to=2026-03-02", headers=m).json()
    today = next(d for d in data["movement"] if d["date"] == "2026-03-02")
    assert today["in"] == 30 and today["out"] >= 8 + 5  # the issue and the transfer out
    assert data["totals"]["breakage_units"] == 2 and data["breakage_by_reason"] == [{"label": "Dropped while carrying", "value": 2}]
    assert data["breakage_top_items"][0]["label"] == "Dinner Plate 27cm"
    assert data["transfers"]["completed"] == 1 and data["transfers"]["units"] == 5
    assert data["transfer_routes"][0]["label"] == "Main Kitchen to Banquet Hall" and data["transfer_routes"][0]["value"] == 5
    assert {t["label"] for t in data["movement_by_type"]} >= {"Receipt", "Issue", "Transfer out"}
    assert data["range"]["grain"] == "day"
    quarter = client.get("/api/stock/insights?date_from=2025-12-15&date_to=2026-03-02", headers=m).json()
    assert quarter["range"]["grain"] == "month" and quarter["movement"][0]["date"] == "2025-12" and len(quarter["movement"]) == 4


def test_insights_respect_location_scope_and_range_limits(client, login, db):
    assert client.get(f"/api/stock/insights?location_id={loc_id(db, 'MK')}", headers=login(SUP_RB)).status_code == 403
    assert client.get("/api/stock/insights?date_from=2020-01-01&date_to=2026-03-02", headers=login(MGR)).status_code == 400
    assert client.get("/api/stock/insights?date_from=2026-03-05&date_to=2026-03-01", headers=login(MGR)).status_code == 400
    assert client.get("/api/stock/insights").status_code == 401


def test_reconciliation_flags_shortages_with_their_value(client, login, db, clock):
    c = count(client, login(SUP), db, 190).json()  # 10 plates short
    client.post(f"/api/stock/counts/{c['id']}/post", headers=login(MGR))
    other = count(client, login(SUP), db, 5, code="KN-001", loc="MK")
    assert other.status_code in (201, 400)
    doc = client.get(f"/api/stock/reconciliation?location_id={loc_id(db, 'MK')}&month=2026-03", headers=login(MGR)).json()
    row_ = next(r for r in doc["rows"] if r["code"] == "PL-001")
    assert row_["count_variance"] == -10 and row_["variance_value"] == -25.0  # 10 x 2.50
    assert doc["variance"]["shortage_items"] == 1 and doc["variance"]["shortage_units"] == 10 and doc["variance"]["net_value"] == -25.0
    assert doc["variance"]["surplus_items"] == 0


def test_a_catch_up_transfer_is_dated_on_the_day_the_stock_really_moved(client, login, db, clock):
    m = login(MGR)
    body = {"from_location_id": loc_id(db, "MK"), "to_location_id": loc_id(db, "BQ"), "lines": [{"item_id": item_id(db, "PL-001"), "qty": 25}],
            "note": "Moved by hand", "moved_on": "2026-02-20"}
    assert client.post("/api/stock/transfers", json=body, headers=login(SUP)).status_code == 403          # only an approver records one
    done = client.post("/api/stock/transfers", json=body, headers=m)
    assert done.status_code == 201 and done.json()["status"] == "completed"
    assert "Catch-up, moved on 2026-02-20" in done.json()["note"] and done.json()["requested_at"].startswith("2026-02-20")
    assert balance(db, "PL-001", "MK") == 175 and balance(db, "PL-001", "BQ") == 175
    moved = db.scalars(select(StockTransaction).where(StockTransaction.ref_type == "transfer")).all()
    assert {t.occurred_at.date().isoformat() for t in moved} == {"2026-02-20"}                            # the ledger carries that day, not today
    assert client.post("/api/stock/transfers", json={**body, "moved_on": "2025-01-01"}, headers=m).status_code == 400   # too long ago
    assert client.post("/api/stock/transfers", json={**body, "moved_on": "2026-03-09"}, headers=m).status_code == 400   # in the future
    # the stock count then sees it as received at the other place
    limits = {l["item_id"]: l for l in client.get(f"/api/stock/count-limits?location_id={loc_id(db, 'BQ')}", headers=m).json()}
    assert limits[item_id(db, "PL-001")]["transfers_in"] >= 25


def test_a_catch_up_cannot_be_dated_before_a_count_that_was_already_posted(client, login, db, clock):
    m = login(MGR)
    mk = loc_id(db, "MK")
    count = client.post("/api/stock/counts", json={"location_id": mk, "lines": [{"item_id": item_id(db, "PL-001"), "counted_qty": 200}]}, headers=m).json()
    assert client.post(f"/api/stock/counts/{count['id']}/post", headers=m).status_code == 200
    body = {"from_location_id": mk, "to_location_id": loc_id(db, "BQ"), "lines": [{"item_id": item_id(db, "PL-001"), "qty": 5}], "moved_on": "2026-02-01"}
    assert client.post("/api/stock/transfers", json=body, headers=m).status_code == 409


def test_a_count_in_progress_is_saved_per_person_and_cleared_when_the_count_is_saved(client, login, db, clock):
    m, sup = login(MGR), login(SUP)
    mk, pl = loc_id(db, "MK"), item_id(db, "PL-001")
    assert client.get(f"/api/stock/count-draft?location_id={mk}", headers=m).json()["entries"] == {}
    saved = client.put("/api/stock/count-draft", json={"location_id": mk, "entries": {str(pl): {"qty": "150", "reason": ""}}}, headers=m)
    assert saved.json() == {"saved": 1}
    assert client.get(f"/api/stock/count-draft?location_id={mk}", headers=m).json()["entries"][str(pl)]["qty"] == "150"
    assert client.get(f"/api/stock/count-draft?location_id={mk}", headers=sup).json()["entries"] == {}      # someone else's is separate
    client.post("/api/stock/counts", json={"location_id": mk, "lines": [{"item_id": pl, "counted_qty": 150}]}, headers=m)
    assert client.get(f"/api/stock/count-draft?location_id={mk}", headers=m).json()["entries"] == {}        # saved for real: working copy gone
    client.put("/api/stock/count-draft", json={"location_id": mk, "entries": {str(pl): {"qty": "9", "reason": ""}}}, headers=m)
    client.put("/api/stock/count-draft", json={"location_id": mk, "entries": {str(pl): {"qty": "", "reason": ""}}}, headers=m)   # emptied
    assert client.get(f"/api/stock/count-draft?location_id={mk}", headers=m).json()["entries"] == {}
