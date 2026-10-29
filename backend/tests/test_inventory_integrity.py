from decimal import Decimal

from sqlalchemy import select

from app.models import InventoryBalance, InventoryItem, Notification

from .helpers import MGR, STEWARD, SUP, item_id, loc_id, retire_item
from .test_stock import count


def held(db, code="PL-001", place="MK"):
    db.expire_all()
    b = db.get(InventoryBalance, (item_id(db, code), loc_id(db, place)))
    return b.qty, b.avg_cost


def post_receipt(client, h, db, discount_percent=None):
    supplier = client.post("/api/suppliers", headers=h, json={"name": "Integrity Supply"}).json()["id"]
    body = {"supplier_id": supplier, "location_id": loc_id(db, "MK"), "invoice_number": "INT-1", "lines": [{"item_id": item_id(db, "PL-001"), "qty": 100, "unit_cost": 10}]}
    if discount_percent:
        body.update(discount_type="percent", discount=discount_percent)
    return client.post("/api/receipts", headers=h, json=body)


def test_voiding_an_invoice_with_a_discount_restores_the_average_cost(client, login, db):
    m = login(MGR)
    start_qty, start_cost = held(db)
    made = post_receipt(client, m, db, discount_percent=20)
    assert made.status_code == 201
    assert held(db)[1] != start_cost
    assert client.post(f"/api/receipts/{made.json()['id']}/void", headers=m, json={"reason": "Entered twice"}).status_code == 200
    qty, cost = held(db)
    assert qty == start_qty and abs(cost - start_cost) < Decimal("0.001")


def test_a_second_count_cannot_be_posted_over_a_correction_already_made(client, login, db):
    m = login(MGR)
    first, second = count(client, m, db, 190).json(), count(client, m, db, 190).json()
    assert client.post(f"/api/stock/counts/{first['id']}/post", headers=m).status_code == 200
    refused = client.post(f"/api/stock/counts/{second['id']}/post", headers=m)
    assert refused.status_code == 409 and "already corrected by count" in refused.json()["detail"]
    assert held(db)[0] == 190


def report(client, h, db, qty):
    return client.post("/api/breakage", headers=h, json={"location_id": loc_id(db, "MK"), "item_id": item_id(db, "PL-001"), "qty": qty,
                                                         "incident_type": "breakage", "reason": "dropped crate"})


def test_a_reviewer_cannot_lower_a_large_breakage_under_the_approval_limit(client, login, db):
    reported = report(client, login(STEWARD), db, 50).json()
    reviewed = client.post(f"/api/breakage/{reported['id']}/review", headers=login(SUP), json={"qty": 1})
    assert reviewed.json()["status"] == "pending_approval"


def test_small_breakages_of_one_item_in_a_day_add_up_to_an_approval(client, login, db):
    s, sup = login(STEWARD), login(SUP)
    first = client.post(f"/api/breakage/{report(client, s, db, 3).json()['id']}/review", headers=sup, json={"qty": 3})
    assert first.json()["status"] == "approved"
    second = client.post(f"/api/breakage/{report(client, s, db, 3).json()['id']}/review", headers=sup, json={"qty": 3})
    assert second.json()["status"] == "pending_approval"


def test_only_a_manager_can_write_off_more_than_the_books_show_and_everyone_is_told(client, login, db):
    sup, m, s = login(SUP), login(MGR), login(STEWARD)
    assert client.post("/api/inventory/transactions", headers=sup, json={"item_id": item_id(db, "PL-001"), "location_id": loc_id(db, "MK"), "txn_type": "issue", "qty": 198}).status_code == 201
    incident = report(client, s, db, 3).json()
    refused = client.post(f"/api/breakage/{incident['id']}/review", headers=sup, json={"qty": 3})
    assert refused.status_code == 409 and "Only a manager" in refused.json()["detail"] and held(db)[0] == 2
    assert client.post(f"/api/breakage/{incident['id']}/review", headers=m, json={"qty": 3}).json()["status"] == "approved"
    assert held(db)[0] == -1
    assert db.scalar(select(Notification).where(Notification.kind == "negative_stock")) is not None


def test_opening_stock_is_recorded_once_per_item_and_place(client, login, db):
    m = login(MGR)
    pl = db.scalar(select(InventoryItem).where(InventoryItem.code == "PL-001"))
    again = client.post("/api/inventory/transactions", headers=m, json={"item_id": pl.id, "location_id": loc_id(db, "MK"), "txn_type": "opening", "qty": 10, "reason": "Entered again"})
    assert again.status_code == 409 and "already recorded" in again.json()["detail"]
    assert held(db)[0] == 200


def test_an_item_with_movements_keeps_its_unit_and_one_with_stock_is_not_retired(client, login, db):
    m = login(MGR)
    pl = db.scalar(select(InventoryItem).where(InventoryItem.code == "PL-001"))
    other_unit = next(u["id"] for u in client.get("/api/inventory/units", headers=m).json() if u["id"] != pl.unit_id)
    changed = client.put(f"/api/inventory/items/{pl.id}", headers=m, json={"unit_id": other_unit})
    assert changed.status_code == 409 and "unit cannot change" in changed.json()["detail"]
    retired = client.put(f"/api/inventory/items/{pl.id}", headers=m, json={"active": False})
    assert retired.status_code == 409 and "still on the books" in retired.json()["detail"]
    assert retire_item(client, m, db, "PL-001").status_code == 200


def test_an_item_with_a_minimum_that_was_never_stocked_shows_as_short(client, login, db):
    m = login(MGR)
    pl = db.scalar(select(InventoryItem).where(InventoryItem.code == "PL-001"))
    made = client.post("/api/inventory/items", headers=m, json={"name": "Never Stocked Spoon", "category_id": pl.category_id, "unit_id": pl.unit_id, "min_level": 20})
    assert made.status_code == 201 and made.json()["low"] is True
    low = client.get("/api/inventory/items", headers=m, params={"search": "Never Stocked", "low_only": True}).json()
    assert low["total"] == 1
    short = [r for r in client.get("/api/inventory/shortages", headers=m).json()["items"] if r["name"] == "Never Stocked Spoon"]
    assert {r["location_id"] for r in short} == {loc_id(db, c) for c in ("MK", "BQ", "RB")} and all(r["qty"] == 0 for r in short)
    assert client.post("/api/inventory/transactions", headers=m, json={"item_id": made.json()["id"], "location_id": loc_id(db, "MK"), "txn_type": "opening", "qty": 25, "reason": "First delivery counted in"}).status_code == 201
    after = client.get("/api/inventory/shortages", headers=m).json()["items"]
    assert not [r for r in after if r["name"] == "Never Stocked Spoon" and r["location_id"] == loc_id(db, "MK")]


def knives(db, place):
    from app.models import TrackedAsset
    db.expire_all()
    return list(db.scalars(select(TrackedAsset).where(TrackedAsset.item_id == item_id(db, "KN-001"), TrackedAsset.location_id == loc_id(db, place)).order_by(TrackedAsset.id)))


def transfer(client, h, db, lines, source="MK", target="BQ"):
    return client.post("/api/stock/transfers", headers=h, json={"from_location_id": loc_id(db, source), "to_location_id": loc_id(db, target), "lines": lines})


def test_a_transfer_of_a_tracked_item_moves_the_tags_named(client, login, db):
    m = login(MGR)
    knife, at_mk = item_id(db, "KN-001"), knives(db, "MK")
    assert len(at_mk) >= 2 and not knives(db, "RB")
    assert transfer(client, m, db, [{"item_id": knife, "qty": 1}]).status_code == 400                                   # no tag named
    assert transfer(client, m, db, [{"item_id": knife, "qty": 2, "asset_ids": [at_mk[0].id]}]).status_code == 400      # too few tags
    assert transfer(client, m, db, [{"item_id": knife, "qty": 1, "asset_ids": [at_mk[0].id, at_mk[0].id]}]).status_code == 400
    plate = item_id(db, "PL-001")
    assert transfer(client, m, db, [{"item_id": plate, "qty": 1, "asset_ids": [at_mk[0].id]}]).status_code == 400      # an untracked item has no tags
    moved = transfer(client, m, db, [{"item_id": knife, "qty": 1, "asset_ids": [at_mk[0].id]}])
    assert moved.status_code == 201 and moved.json()["lines"][0]["asset_tags"] == [at_mk[0].asset_tag]
    assert at_mk[0].id in {a.id for a in knives(db, "BQ")} and at_mk[0].id not in {a.id for a in knives(db, "MK")}
    assert transfer(client, m, db, [{"item_id": knife, "qty": 1, "asset_ids": [at_mk[0].id]}]).status_code == 400      # it is no longer at MK


def test_a_requested_transfer_moves_the_tags_only_when_approved(client, login, db):
    knife, at_mk = item_id(db, "KN-001"), knives(db, "MK")
    asked = transfer(client, login(SUP), db, [{"item_id": knife, "qty": 1, "asset_ids": [at_mk[0].id]}])
    assert asked.status_code == 201 and asked.json()["status"] == "requested"
    assert at_mk[0].id in {a.id for a in knives(db, "MK")}
    assert client.post(f"/api/stock/transfers/{asked.json()['id']}/decision", headers=login(MGR), json={"approve": True}).status_code == 200
    assert at_mk[0].id in {a.id for a in knives(db, "BQ")}
