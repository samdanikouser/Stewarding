from sqlalchemy import select

from app.models import InventoryBalance, Notification, StockTransaction

from .helpers import MGR, SUP, balance, item_id, ledger_sum, loc_id

LOCS = ("MK", "BQ", "RB")


def start(client, h, db, **over):
    return client.post("/api/rounds", json={"name": "November count", **over}, headers=h)


def put(client, h, db, rid, code, entries):
    return client.put(f"/api/rounds/{rid}/counts/{loc_id(db, code)}", json={"entries": {str(i): {"qty": str(q), "reason": r} for i, (q, r) in entries.items()}}, headers=h)


def finish_all(client, h, db, rid):
    for code in LOCS:
        r = client.post(f"/api/rounds/{rid}/counts/{loc_id(db, code)}/done", headers=h)
        assert r.status_code == 200, r.text


def row(client, h, rid, item):
    return next(r for r in client.get(f"/api/rounds/{rid}/review", headers=h).json()["rows"] if r["item_id"] == item)


def test_only_a_manager_starts_a_round_and_only_one_can_be_open(client, login, db, clock):
    assert start(client, login(SUP), db).status_code == 403
    made = start(client, login(MGR), db)
    assert made.status_code == 201 and {p["status"] for p in made.json()["locations"]} == {"counting"}
    assert start(client, login(MGR), db).status_code == 409


def test_the_pool_check_refuses_counts_that_add_up_to_more_than_was_received(client, login, db, clock):
    m = login(MGR)
    rid = start(client, m, db).json()["id"]
    pl = item_id(db, "PL-001")
    sheet = client.get(f"/api/rounds/{rid}/entry?location_id={loc_id(db, 'BQ')}", headers=m).json()
    line = next(i for i in sheet["items"] if i["item_id"] == pl)
    assert line["received"] == line["book"] and line["allowance"] == line["received"] and line["others"] == 0
    received = line["received"]
    assert put(client, m, db, rid, "MK", {pl: (received - 10, "")}).json()["refused"] == []
    again = client.get(f"/api/rounds/{rid}/entry?location_id={loc_id(db, 'BQ')}", headers=m).json()
    assert next(i for i in again["items"] if i["item_id"] == pl)["allowance"] == 10                    # what is left for the others
    refused = put(client, m, db, rid, "BQ", {pl: (11, "")}).json()
    assert refused["saved"] == 0 and "At most 10" in refused["refused"][0]["message"]
    assert db.scalar(select(Notification.id).where(Notification.kind == "count_over_received"))
    assert put(client, m, db, rid, "BQ", {pl: (10, "")}).json()["refused"] == []                        # exactly the rest is fine


def test_a_round_is_reviewed_approved_and_posted_so_stock_matches_the_counts_with_the_gap_as_usage(client, login, db, clock):
    m = login(MGR)
    rid = start(client, m, db).json()["id"]
    pl = item_id(db, "PL-001")
    before = {c: balance(db, "PL-001", c) for c in LOCS}
    total = sum(before.values())
    counts = {"MK": 120, "BQ": 90, "RB": 30}                                                            # 240 found, the rest is unaccounted
    for code, qty in counts.items():
        assert put(client, m, db, rid, code, {pl: (qty, "")}).json()["refused"] == []
    assert client.post(f"/api/rounds/{rid}/post", headers=m).status_code == 409                          # not everyone is done
    finish_all(client, m, db, rid)
    r = row(client, m, rid, pl)
    assert r["book"] == total and r["counted"] == 240 and r["unaccounted"] == total - 240 and r["state"] == "needs_review"
    assert client.post(f"/api/rounds/{rid}/post", headers=m).status_code == 409                          # the manager has not approved it
    assert client.post(f"/api/rounds/{rid}/approve", json={"item_ids": [pl]}, headers=login(SUP)).status_code == 403
    assert client.post(f"/api/rounds/{rid}/approve", json={"item_ids": [pl]}, headers=m).json() == {"approved": 1}
    # every other item was not counted at all, so their gaps need approving too
    client.post(f"/api/rounds/{rid}/approve", json={"item_ids": [x["item_id"] for x in client.get(f"/api/rounds/{rid}/review", headers=m).json()["rows"]]}, headers=m)
    done = client.post(f"/api/rounds/{rid}/post", headers=m)
    assert done.status_code == 200 and done.json()["status"] == "posted"
    for code, qty in counts.items():
        assert balance(db, "PL-001", code) == qty == ledger_sum(db, "PL-001", code)                       # each location now holds what was counted
    usage = db.scalars(select(StockTransaction).where(StockTransaction.item_id == pl, StockTransaction.ref_type == "count_round", StockTransaction.txn_type == "adjustment")).all()
    assert sum(t.qty_delta for t in usage) == -(total - 240)                                              # the unaccounted stock left as usage
    cost = client.get(f"/api/stock/cost-report?date_from=2026-03-01&date_to=2026-03-31", headers=m).json()["totals"]
    assert cost["cost_consumed"] > 0 and round(cost["cost_consumed"], 3) == round(-cost["count_adjustments"], 3)


def test_a_baseline_round_takes_the_gap_as_the_starting_point_not_as_a_cost(client, login, db, clock):
    m = login(MGR)
    rid = start(client, m, db).json()["id"]
    pl = item_id(db, "PL-001")
    put(client, m, db, rid, "MK", {pl: (50, "")})
    finish_all(client, m, db, rid)
    client.post(f"/api/rounds/{rid}/approve", json={"item_ids": [x["item_id"] for x in client.get(f"/api/rounds/{rid}/review", headers=m).json()["rows"]]}, headers=m)
    assert client.post(f"/api/rounds/{rid}/post", json={"baseline": True}, headers=m).status_code == 200
    cost = client.get("/api/stock/cost-report?date_from=2026-03-01&date_to=2026-03-31", headers=m).json()["totals"]
    assert cost["cost_consumed"] == 0                                                                    # nothing was charged to cost


def test_a_recount_reopens_the_locations_and_blocks_posting_until_the_number_changes(client, login, db, clock):
    m = login(MGR)
    rid = start(client, m, db).json()["id"]
    pl = item_id(db, "PL-001")
    put(client, m, db, rid, "MK", {pl: (100, "")})
    finish_all(client, m, db, rid)
    assert client.post(f"/api/rounds/{rid}/recount", json={"item_ids": [pl], "note": "Looks low"}, headers=m).status_code == 200
    assert {p["status"] for p in client.get(f"/api/rounds/{rid}", headers=m).json()["locations"]} == {"counting"}
    assert row(client, m, rid, pl)["state"] == "recount"
    put(client, m, db, rid, "MK", {pl: (160, "")})                                                       # corrected: the decision is cleared
    assert row(client, m, rid, pl)["state"] != "recount"


def test_a_count_above_the_books_is_refused_until_the_found_stock_is_recorded(client, login, db, clock):
    m = login(MGR)
    pl = item_id(db, "PL-001")
    # 20 used and written off: received 390, the books now hold 370, and that is the most that can be counted in all
    client.post("/api/inventory/transactions", json={"item_id": pl, "location_id": loc_id(db, "MK"), "txn_type": "issue", "qty": 20, "reason": "used"}, headers=m)
    rid = start(client, m, db).json()["id"]
    mine = next(i for i in client.get(f"/api/rounds/{rid}/entry?location_id={loc_id(db, 'MK')}", headers=m).json()["items"] if i["item_id"] == pl)
    assert mine["received"] == 390 and mine["book"] == 370 and mine["allowance"] == 370              # the limit follows the books, not the lifetime received
    refused = put(client, m, db, rid, "MK", {pl: (375, "I found a box")}).json()
    assert refused["saved"] == 0 and "370 the books hold" in refused["refused"][0]["message"]       # a reason is not enough to enter more than that
    assert put(client, m, db, rid, "MK", {pl: (370, "")}).json()["refused"] == []
    # the stock really was found: a manager records it, then the count can include it
    assert client.post("/api/inventory/transactions", json={"item_id": pl, "location_id": loc_id(db, "MK"), "txn_type": "adjustment", "qty": 5, "reason": "Found a box in the back store"}, headers=m).status_code == 201
    assert put(client, m, db, rid, "MK", {pl: (375, "")}).json()["refused"] == []
    assert client.post("/api/inventory/transactions", json={"item_id": pl, "location_id": loc_id(db, "MK"), "txn_type": "adjustment", "qty": 5, "reason": "x"}, headers=login(SUP)).status_code == 403   # only a manager can add found stock


def test_within_tolerance_gaps_are_approved_together(client, login, db, clock):
    m = login(MGR)
    rid = start(client, m, db).json()["id"]
    pn = item_id(db, "PN-001")
    for code in ("MK", "BQ", "RB"):
        put(client, m, db, rid, code, {pn: (balance(db, "PN-001", code) - (1 if code == "BQ" else 0), "")})   # one short at one outlet
    near = row(client, m, rid, pn)
    assert near["unaccounted"] == 1 and near["within_tolerance"] and near["state"] == "within_tolerance"
    assert client.post(f"/api/rounds/{rid}/approve", json={"within_tolerance": True}, headers=m).json()["approved"] >= 1
    assert row(client, m, rid, pn)["state"] == "approved"


def test_a_round_that_wrote_stock_off_lowers_the_limit_for_the_next_round(client, login, db, clock):
    m = login(MGR)
    pl = item_id(db, "PL-001")
    first = start(client, m, db).json()["id"]
    counts = {"MK": 100, "BQ": 50, "RB": 20}                                                          # 170 found of 390: 220 written off
    for code, qty in counts.items():
        put(client, m, db, first, code, {pl: (qty, "")})
    finish_all(client, m, db, first)
    approve_everything(client, m, first)
    assert client.post(f"/api/rounds/{first}/post", headers=m).status_code == 200
    second = start(client, m, db).json()["id"]
    over = put(client, m, db, second, "MK", {pl: (300, "")}).json()                                  # the written-off stock cannot simply come back
    assert over["saved"] == 0 and "170 the books hold" in over["refused"][0]["message"]


def test_a_location_that_has_not_finished_is_reminded_from_the_deadline(client, login, db, clock):
    from app.services.alerts import run_alerts
    m = login(MGR)
    rid = start(client, m, db, deadline="2026-03-03").json()["id"]
    run_alerts(db, clock.now)                                                                            # 2 March: before the deadline
    db.commit()
    assert db.scalars(select(Notification).where(Notification.kind == "round_overdue")).all() == []
    clock.set(2026, 3, 3, 12, 0)
    client.post(f"/api/rounds/{rid}/counts/{loc_id(db, 'MK')}/done", headers=m)                         # the main kitchen is done
    run_alerts(db, clock.now)
    db.commit()
    db.expire_all()
    late = db.scalars(select(Notification).where(Notification.kind == "round_overdue")).all()
    assert late and all("Main Kitchen" not in n.title for n in late) and any("Banquet" in n.title for n in late)


def test_a_posted_round_still_shows_what_it_did(client, login, db, clock):
    m = login(MGR)
    rid = start(client, m, db).json()["id"]
    pl = item_id(db, "PL-001")
    put(client, m, db, rid, "MK", {pl: (100, "")})
    finish_all(client, m, db, rid)
    client.post(f"/api/rounds/{rid}/approve", json={"item_ids": [x["item_id"] for x in client.get(f"/api/rounds/{rid}/review", headers=m).json()["rows"]]}, headers=m)
    book = row(client, m, rid, pl)["book"]
    assert client.post(f"/api/rounds/{rid}/post", headers=m).status_code == 200
    after = client.get(f"/api/rounds/{rid}/review", headers=m).json()
    shown = next(r for r in after["rows"] if r["item_id"] == pl)
    assert shown["counted"] == 100 and shown["unaccounted"] == book - 100 and shown["book"] == book and after["shortage_value"] > 0
    assert client.get(f"/api/rounds/{rid}/report.csv", headers=m).status_code == 200


def approve_everything(client, h, rid):
    rows = client.get(f"/api/rounds/{rid}/review", headers=h).json()["rows"]
    client.post(f"/api/rounds/{rid}/approve", json={"item_ids": [r["item_id"] for r in rows]}, headers=h)


def test_a_delivery_after_the_count_is_not_a_gap_and_survives_posting(client, login, db, clock):
    from .test_receiving import receive
    m = login(MGR)
    rid = start(client, m, db).json()["id"]
    pl = item_id(db, "PL-001")
    found = {c: balance(db, "PL-001", c) for c in LOCS}
    for code, qty in found.items():
        put(client, m, db, rid, code, {pl: (qty, "")})                                                    # everything found
    finish_all(client, m, db, rid)
    clock.advance(hours=3)
    assert receive(client, m, db, [{"item_id": pl, "qty": 10, "unit_cost": 2.0}], invoice="AFTER-1").status_code == 201   # arrives after the count
    seen = row(client, m, rid, pl)
    assert seen["unaccounted"] == 0 and seen["state"] == "balanced"                                       # not a shortage, and not hidden inside the tolerance
    approve_everything(client, m, rid)
    assert client.post(f"/api/rounds/{rid}/post", headers=m).status_code == 200
    assert sum(balance(db, "PL-001", c) for c in LOCS) == sum(found.values()) + 10                          # the delivery is still there


def test_items_nobody_counted_are_flagged_and_never_slip_through_the_within_tolerance_approval(client, login, db, clock):
    m = login(MGR)
    rid = start(client, m, db).json()["id"]
    pn = item_id(db, "PN-001")                                                                            # 9 held in all: a gap of 9 is not within 2 units or 5%
    finish_all(client, m, db, rid)
    seen = row(client, m, rid, pn)
    assert seen["state"] == "not_counted" and seen["not_counted"] and not seen["within_tolerance"]
    client.post(f"/api/rounds/{rid}/approve", json={"within_tolerance": True}, headers=m)
    assert row(client, m, rid, pn)["state"] == "not_counted"                                              # still waiting for a person to look at it
    small = item_id(db, "KN-001")                                                                         # even a small skipped item is not auto-approved
    assert not row(client, m, rid, small)["within_tolerance"]


def test_the_shortage_value_in_review_is_what_posting_charges(client, login, db, clock):
    m = login(MGR)
    rid = start(client, m, db).json()["id"]
    pl = item_id(db, "PL-001")
    put(client, m, db, rid, "MK", {pl: (100, "")})
    finish_all(client, m, db, rid)
    approve_everything(client, m, rid)
    shown = client.get(f"/api/rounds/{rid}/review", headers=m).json()["shortage_value"]
    assert client.post(f"/api/rounds/{rid}/post", headers=m).status_code == 200
    cost = client.get("/api/stock/cost-report?date_from=2026-03-01&date_to=2026-03-31", headers=m).json()["totals"]
    assert abs(cost["cost_consumed"] - shown) < 0.01


def test_a_location_added_after_the_round_started_is_left_alone(client, login, db, clock):
    from app.models import Location
    m = login(MGR)
    rid = start(client, m, db).json()["id"]
    late = Location(code="NEW", name="Late Outlet", kind="outlet", timezone="Asia/Dubai", active=True)
    db.add(late)
    db.flush()
    pl = item_id(db, "PL-001")
    db.add(InventoryBalance(item_id=pl, location_id=late.id, qty=7))
    db.commit()
    finish_all(client, m, db, rid)
    approve_everything(client, m, rid)
    assert client.post(f"/api/rounds/{rid}/post", headers=m).status_code == 200
    assert db.get(InventoryBalance, (pl, late.id)).qty == 7                                                # not part of the round, so not written off


def test_the_report_has_opening_and_closing_for_every_item_in_every_location(client, login, db, clock):
    import csv, io
    m = login(MGR)
    rid = start(client, m, db).json()["id"]
    pl = item_id(db, "PL-001")
    before = {c: balance(db, "PL-001", c) for c in LOCS}
    counts = {"MK": 120, "BQ": 90, "RB": 30}
    for code, qty in counts.items():
        put(client, m, db, rid, code, {pl: (qty, "")})
    finish_all(client, m, db, rid)
    live = next(r for r in client.get(f"/api/rounds/{rid}/review", headers=m).json()["rows"] if r["item_id"] == pl)
    detail = {x["location"]: x for x in live["locations"]}
    assert detail["Main Kitchen"] == {"location": "Main Kitchen", "opening": before["MK"], "counted": 120, "difference": 120 - before["MK"]}
    assert detail["Banquet Hall"]["opening"] == before["BQ"] and detail["Banquet Hall"]["counted"] == 90

    def table():
        text = client.get(f"/api/rounds/{rid}/report.csv", headers=m).text.lstrip("﻿")
        rows = list(csv.reader(io.StringIO(text)))
        head, body = rows[0], rows[1:]
        return head, next(r for r in body if r[0] == "PL-001")

    head, line = table()
    col = {name: i for i, name in enumerate(head)}
    assert line[col["Main Kitchen opening"]] == str(before["MK"]) and line[col["Main Kitchen counted (closing)"]] == "120"
    assert line[col["Banquet Hall difference"]] == str(90 - before["BQ"]) and line[col["Counted total"]] == "240"
    approve_everything(client, m, rid)
    assert client.post(f"/api/rounds/{rid}/post", headers=m).status_code == 200
    head, line = table()                                                                               # after posting the same table is rebuilt from the ledger
    col = {name: i for i, name in enumerate(head)}
    assert line[col["Main Kitchen opening"]] == str(before["MK"]) and line[col["Main Kitchen counted (closing)"]] == "120"
    assert line[col["Rooftop Bar opening"]] == str(before["RB"]) and line[col["Rooftop Bar counted (closing)"]] == "30"


def test_a_baseline_round_keeps_opening_stock_true_and_shows_its_gap_as_its_own_line(client, login, db, clock):
    m = login(MGR)
    mk, pl = loc_id(db, "MK"), item_id(db, "PL-001")
    opening = balance(db, "PL-001", "MK")
    pool = sum(balance(db, "PL-001", c) for c in LOCS)
    rid = start(client, m, db).json()["id"]
    put(client, m, db, rid, "MK", {pl: (50, "")})
    finish_all(client, m, db, rid)
    approve_everything(client, m, rid)
    assert client.post(f"/api/rounds/{rid}/post", json={"baseline": True}, headers=m).status_code == 200
    report = client.get(f"/api/stock/cost-report?date_from=2026-03-01&date_to=2026-03-31&location_id={mk}", headers=m).json()
    line = next(r for r in report["rows"] if r["item_id"] == pl)
    assert line["opening_qty"] == opening and line["closing_qty"] == 50                                    # opening is what it was; the gap is not hidden in it
    assert line["baseline_adjustments_qty"] == 50 - opening and report["totals"]["baseline_adjustments"] < 0          # each place carries its own gap
    assert report["totals"]["cost_consumed"] == 0


def test_allocation_needs_no_main_store_it_moves_found_units_from_where_the_books_hold_more():
    from app.api.rounds import allocate
    # everything booked in one place, counted across three
    assert allocate({1: 100}, {1: 60, 2: 20, 3: 10}) == ([(1, 2, 20), (1, 3, 10)], {1: -10})
    # an outlet received directly and the books already match
    assert allocate({1: 0, 2: 50}, {1: 0, 2: 50}) == ([], {})
    # some booked at the store, some at the outlet; the outlet found more, the store less
    assert allocate({1: 100, 2: 30}, {1: 70, 2: 50}) == ([(1, 2, 20)], {1: -10})
    # more was found in total than the books held (approved with a reason): the extra is written on where it was found
    assert allocate({1: 10}, {1: 10, 2: 3}) == ([], {2: 3})
    # nothing found anywhere: every place carries its own shortage
    assert allocate({1: 5, 2: 4}, {}) == ([], {1: -5, 2: -4})


def test_a_round_posts_with_stock_booked_in_one_place_and_counted_in_several(client, login, db, clock):
    m = login(MGR)
    rid = start(client, m, db).json()["id"]                                                            # no main store is chosen
    pl = item_id(db, "PL-001")
    books = {c: balance(db, "PL-001", c) for c in LOCS}                                                 # MK 200, BQ 150, RB 40
    counts = {"MK": 20, "BQ": books["BQ"] + 50, "RB": 30}                                               # BQ found 50 more than its books: they were booked at MK
    for code, qty in counts.items():
        assert put(client, m, db, rid, code, {pl: (qty, "")}).json()["refused"] == []
    finish_all(client, m, db, rid)
    seen = row(client, m, rid, pl)
    assert seen["unaccounted"] == sum(books.values()) - sum(counts.values())
    approve_everything(client, m, rid)
    assert client.post(f"/api/rounds/{rid}/post", headers=m).status_code == 200
    for code, qty in counts.items():
        assert balance(db, "PL-001", code) == qty == ledger_sum(db, "PL-001", code)
    moved = [t for t in db.scalars(select(StockTransaction).where(StockTransaction.item_id == pl, StockTransaction.ref_type == "count_round"))]
    assert sum(t.qty_delta for t in moved if t.txn_type in ("transfer_in", "transfer_out")) == 0       # moved units are not created or lost
    assert sum(t.qty_delta for t in moved if t.txn_type == "adjustment") == -(sum(books.values()) - sum(counts.values()))


def test_the_first_round_asks_whether_its_gap_is_the_starting_point_and_later_rounds_never_can_take_it_so(client, login, db, clock):
    m = login(MGR)
    pl = item_id(db, "PL-001")
    first = start(client, m, db).json()["id"]
    assert client.get(f"/api/rounds/{first}/review", headers=m).json()["first_round"] is True
    put(client, m, db, first, "MK", {pl: (100, "")})
    finish_all(client, m, db, first)
    approve_everything(client, m, first)
    assert client.post(f"/api/rounds/{first}/post", json={"baseline": True}, headers=m).status_code == 200
    second = start(client, m, db).json()["id"]
    assert client.get(f"/api/rounds/{second}/review", headers=m).json()["first_round"] is False
    put(client, m, db, second, "MK", {pl: (50, "")})
    finish_all(client, m, db, second)
    approve_everything(client, m, second)
    wrong = client.post(f"/api/rounds/{second}/post", json={"baseline": True}, headers=m)
    assert wrong.status_code == 400 and "first round" in wrong.json()["detail"]
    assert client.post(f"/api/rounds/{second}/post", json={"baseline": False}, headers=m).status_code == 200


def test_the_count_sheet_shows_what_the_books_hold_at_that_location_and_a_transfer_in_adds_to_it(client, login, db, clock):
    m = login(MGR)
    pl = item_id(db, "PL-001")
    rid = start(client, m, db).json()["id"]

    def here(code):
        sheet = client.get(f"/api/rounds/{rid}/entry?location_id={loc_id(db, code)}", headers=m).json()
        return next(i for i in sheet["items"] if i["item_id"] == pl)["here"]

    before = here("BQ")
    assert before == balance(db, "PL-001", "BQ")
    done = client.post("/api/stock/transfers", json={"from_location_id": loc_id(db, "MK"), "to_location_id": loc_id(db, "BQ"), "lines": [{"item_id": pl, "qty": 30}]}, headers=m)
    assert done.status_code == 201
    assert here("BQ") == before + 30 and here("MK") == balance(db, "PL-001", "MK")                      # the outlet now says 30 more, the store 30 less
    put(client, m, db, rid, "BQ", {pl: (before + 30, "")})                                                # found exactly what the books say
    finish_all(client, m, db, rid)
    assert row(client, m, rid, pl)["by_location"]["Banquet Hall"] == before + 30
