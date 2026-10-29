from .helpers import MGR, STEWARD, SUP, balance, item_id, loc_id
from .test_receiving import receive


def story(client, h, item, **q):
    qs = "&".join(f"{k}={v}" for k, v in q.items())
    return client.get(f"/api/inventory/items/{item}/history?{qs}", headers=h)


def test_an_items_whole_story_adds_up_and_keeps_received_apart_from_adjustments(client, login, db, clock):
    m = login(MGR)
    mk, bq, pl = loc_id(db, "MK"), loc_id(db, "BQ"), item_id(db, "PL-001")
    start = balance(db, "PL-001", "MK") + balance(db, "PL-001", "BQ") + balance(db, "PL-001", "RB")
    bought = receive(client, m, db, [{"item_id": pl, "qty": 30, "unit_cost": 2.0}], invoice="HS-1").json()
    receive(client, m, db, [{"item_id": pl, "qty": 5, "unit_cost": 2.0}], invoice="HS-R", doc_type="supplier_return")
    client.post(f"/api/receipts/{bought['id']}/void", json={"reason": "entered twice"}, headers=m)
    receive(client, m, db, [{"item_id": pl, "qty": 12, "unit_cost": 2.0}], invoice="HS-2")
    client.post("/api/inventory/transactions", json={"item_id": pl, "location_id": mk, "txn_type": "issue", "qty": 3, "reason": "used"}, headers=m)
    count = client.post("/api/stock/counts", json={"location_id": mk, "lines": [{"item_id": pl, "counted_qty": balance(db, "PL-001", "MK") - 4}]}, headers=m).json()
    client.post(f"/api/stock/counts/{count['id']}/post", headers=m)

    data = story(client, m, pl).json()
    kinds = {t["kind"]: t["qty"] for t in data["totals"]}
    assert kinds["opening"] == start and kinds["received"] == 30 + 12 and kinds["invoice_void"] == -30 and kinds["supplier_return"] == -5
    assert kinds["issue"] == -3 and kinds["count_adjustment"] == -4
    assert data["received_net"] == 30 + 12 - 30 - 5                                                  # what was really received, net of voids and returns
    assert data["closing"] == data["on_hand_now"] == start + 7 - 3 - 4 and data["adds_up"] is True   # the story ends where the shelves are
    ordered = list(reversed(data["rows"]))
    assert ordered[0]["balance"] == ordered[0]["qty"] and ordered[-1]["balance"] == data["closing"]  # a running balance from the first entry
    labels = {r["document"] for r in data["rows"] if r["document"]}
    assert any(d.startswith("Invoice HS-1") for d in labels) and f"Physical count #{count['id']}" in labels
    assert next(r for r in data["rows"] if r["kind"] == "count_adjustment")["reason"].startswith("Physical count")


def test_the_story_can_be_narrowed_by_place_and_dates_and_exported(client, login, db, clock):
    m = login(MGR)
    pl = item_id(db, "PL-001")
    only_bq = story(client, m, pl, location_id=loc_id(db, "BQ")).json()
    assert only_bq["closing"] == only_bq["on_hand_now"] == balance(db, "PL-001", "BQ")
    later = story(client, m, pl, date_from="2030-01-01").json()
    assert later["rows"] == [] and later["opening_balance"] == later["closing"]                        # nothing after that date; the balance carries over
    csv = client.get(f"/api/inventory/items/{pl}/history.csv", headers=m)
    assert csv.status_code == 200 and "Opening stock" in csv.text and csv.text.startswith("﻿")


def test_only_people_who_can_open_inventory_see_the_story_and_supervisors_see_their_own_locations(client, login, db, clock):
    pl = item_id(db, "PL-001")
    assert story(client, login(STEWARD), pl).status_code == 403
    h = login(SUP)
    mine = {loc["code"] for loc in client.get("/api/auth/me", headers=h).json()["locations"]}
    assert story(client, h, pl).json()["closing"] == sum(balance(db, "PL-001", code) for code in mine)   # only the supervisor's own locations
    assert story(client, login(MGR), 99999).status_code == 404
