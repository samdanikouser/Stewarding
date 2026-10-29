from datetime import timedelta

from sqlalchemy import select

from app.models import AuditLog, Lot, LotEvent, Supplier

from .helpers import MGR, STEWARD, SUP, SUP_RB, loc_id
from .test_custom_roles import hire, make_role
from .test_two_step_logs import checks, finish, make

LOTS = "/api/lots"


def food(client, m, name="Chicken breast", group="poultry"):
    made = client.post(f"{LOTS}/food-items", headers=m, json={"name": name, "food_group": group})
    assert made.status_code == 201
    return made.json()["id"]


def rule(client, m, group="poultry", condition="vacuum_chilled", hours=96):
    assert client.put(f"{LOTS}/rules", headers=m, json={"food_group": group, "condition": condition, "hours": hours}).status_code == 200


def a_supplier(db):
    row = db.scalar(select(Supplier))
    if row is None:
        row = Supplier(name="Test Supplier", name_key="test supplier")
        db.add(row)
        db.commit()
    return row.id


def receive(client, h, db, item, **over):
    body = {"food_item_id": item, "supplier_id": a_supplier(db), "location_id": loc_id(db, "MK"), "condition": "chilled_raw", "supplier_lot": "B2610-884",
            "produced_on": "2026-02-27", "expiry_on": "2026-03-10", "temp_c": 2.5, **over}
    return client.post(LOTS, headers=h, json=body)


def butcher(client, db, m):
    make_role(client, m, label="Butcher", tier="steward", permissions=["dashboard.view", "lot.view", "lot.split", "temp.record"])
    return hire(client, db, m, "butcher", "butcher@example.com")


def part(**over):
    return {"description": "200 g breast portions, vacuum", "count": 24, "condition": "vacuum_chilled", **over}


def test_receiving_makes_a_numbered_lot_with_the_supplier_details_and_a_use_by(client, login, db, clock):
    m, sup = login(MGR), login(SUP)
    item = food(client, m)
    supplier = client.post("/api/suppliers", headers=m, json={"name": "Al Wazzan Poultry"}).json()["id"]
    first = receive(client, sup, db, item, supplier_id=supplier)
    assert first.status_code == 201
    lot = first.json()
    assert lot["code"] == "B2610-884" and lot["supplier"] == "Al Wazzan Poultry" and lot["supplier_lot"] == "B2610-884"
    assert (lot["produced_on"], lot["expiry_on"], lot["kind"], lot["status"], lot["temp_c"]) == ("2026-02-27", "2026-03-10", "received", "active", 2.5)
    assert lot["use_by"] == "2026-03-10T20:00:00Z"                       # no rule yet: the end of the supplier's expiry day, Dubai time
    assert receive(client, sup, db, item).json()["code"] == "B2610-884-B"
    rule(client, m, condition="chilled_raw", hours=48)
    assert receive(client, sup, db, item).json()["use_by"] == "2026-03-04T02:05:00Z"   # the rule is earlier than the expiry
    assert receive(client, sup, db, item, expiry_on=None, produced_on=None).json()["use_by"] == "2026-03-04T02:05:00Z"


def test_only_the_right_roles_receive_split_and_manage(client, login, db, clock):
    m, sup = login(MGR), login(SUP)
    item = food(client, m)
    rule(client, m)
    cook = butcher(client, db, m)
    assert receive(client, login(STEWARD), db, item).status_code == 403
    assert receive(client, cook, db, item).status_code == 403
    lot = receive(client, sup, db, item).json()
    assert client.post(f"{LOTS}/{lot['id']}/split", headers=sup, json={"parts": [part()]}).status_code == 403   # a supervisor does not split
    assert client.post(f"{LOTS}/{lot['id']}/split", headers=cook, json={"parts": [part()]}).status_code == 201
    assert client.put(f"{LOTS}/rules", headers=cook, json={"food_group": "poultry", "condition": "frozen", "hours": 5}).status_code == 403
    assert client.post(f"{LOTS}/food-items", headers=sup, json={"name": "Lamb", "food_group": "red_meat"}).status_code == 403
    assert client.get(f"{LOTS}/{lot['id']}", headers=login(STEWARD)).status_code == 403


def test_a_split_needs_a_shelf_life_rule_and_the_portions_keep_the_original_facts(client, login, db, clock):
    m, sup = login(MGR), login(SUP)
    item = food(client, m)
    supplier = client.post("/api/suppliers", headers=m, json={"name": "Al Wazzan Poultry"}).json()["id"]
    cook = butcher(client, db, m)
    lot = receive(client, sup, db, item, supplier_id=supplier, expiry_on="2026-03-06").json()
    blocked = client.post(f"{LOTS}/{lot['id']}/split", headers=cook, json={"parts": [part()]})
    assert blocked.status_code == 409 and "shelf-life rule" in blocked.json()["detail"]
    rule(client, m, hours=24)
    clock.advance(minutes=30)
    two = [part(), part(description="Whole fillets, tray", count=2, condition="chilled_raw")]
    assert client.post(f"{LOTS}/{lot['id']}/split", headers=cook, json={"parts": two}).status_code == 409   # no rule for chilled raw yet
    rule(client, m, condition="chilled_raw", hours=12)
    made = client.post(f"{LOTS}/{lot['id']}/split", headers=cook, json={"parts": two})
    assert made.status_code == 201
    first, second = made.json()["lots"]
    assert (first["code"], second["code"]) == ("B2610-884-1", "B2610-884-2") and first["kind"] == "portion"
    assert first["supplier"] == "Al Wazzan Poultry" and first["supplier_lot"] == "B2610-884" and first["produced_on"] == "2026-02-27" and first["expiry_on"] == "2026-03-06"
    assert first["use_by"] == "2026-03-03T02:35:00Z" and second["use_by"] == "2026-03-02T14:35:00Z"      # 24 h and 12 h from the split
    assert (first["pack_count"], first["pack_description"]) == (24, "200 g breast portions, vacuum")
    assert made.json()["parent"]["status"] == "active"


def test_a_portion_never_outlives_its_parent_and_only_a_manager_may_extend_it(client, login, db, clock):
    m, sup = login(MGR), login(SUP)
    item = food(client, m)
    rule(client, m, hours=500)
    cook = butcher(client, db, m)
    lot = receive(client, sup, db, item, expiry_on="2026-03-05").json()
    child = client.post(f"{LOTS}/{lot['id']}/split", headers=cook, json={"parts": [part()]}).json()["lots"][0]
    assert child["use_by"] == lot["use_by"]                              # the parent's shorter date wins over a 500 hour rule
    sooner = (clock.now + timedelta(hours=5)).isoformat() + "Z"
    assert client.post(f"{LOTS}/{lot['id']}/split", headers=cook, json={"parts": [part(use_by=sooner)]}).json()["lots"][0]["use_by"] == sooner
    later = (clock.now + timedelta(days=30)).isoformat() + "Z"
    assert client.post(f"{LOTS}/{lot['id']}/split", headers=cook, json={"parts": [part(use_by=later)]}).status_code == 403
    assert client.post(f"{LOTS}/{lot['id']}/split", headers=m, json={"parts": [part(use_by=later)]}).status_code == 201
    assert client.post(f"{LOTS}/{lot['id']}/split", headers=cook, json={"parts": [part(use_by="2020-01-01T00:00:00Z")]}).status_code == 400


def test_a_lot_on_hold_used_up_or_past_its_use_by_cannot_be_split(client, login, db, clock):
    m, sup = login(MGR), login(SUP)
    item = food(client, m)
    rule(client, m)
    cook = butcher(client, db, m)
    held = receive(client, sup, db, item).json()
    assert client.post(f"{LOTS}/{held['id']}/status", headers=m, json={"status": "on_hold"}).status_code == 400          # needs a reason
    assert client.post(f"{LOTS}/{held['id']}/status", headers=cook, json={"status": "on_hold", "note": "Supplier recall"}).status_code == 403
    assert client.post(f"{LOTS}/{held['id']}/status", headers=m, json={"status": "on_hold", "note": "Supplier recall"}).status_code == 200
    blocked = client.post(f"{LOTS}/{held['id']}/split", headers=cook, json={"parts": [part()]})
    assert blocked.status_code == 409 and "on hold" in blocked.json()["detail"]
    assert client.post(f"{LOTS}/{held['id']}/status", headers=m, json={"status": "active"}).status_code == 200
    assert client.post(f"{LOTS}/{held['id']}/split", headers=cook, json={"parts": [part()], "finish_parent": True}).status_code == 201
    assert client.get(f"{LOTS}/{held['id']}", headers=m).json()["lot"]["status"] == "used_up"
    assert client.post(f"{LOTS}/{held['id']}/split", headers=cook, json={"parts": [part()]}).status_code == 409
    old = receive(client, sup, db, item).json()
    clock.advance(days=20)
    assert "past its use-by" in client.post(f"{LOTS}/{old['id']}/split", headers=cook, json={"parts": [part()]}).json()["detail"]
    events = [e.detail for e in db.scalars(select(LotEvent).where(LotEvent.lot_id == held["id"]).order_by(LotEvent.id))]
    assert any("on hold" in e and "Supplier recall" in e for e in events) and any("Split into" in e for e in events)


def test_the_butcher_can_discard_but_not_hold_and_nothing_is_ever_deleted(client, login, db, clock):
    m, sup = login(MGR), login(SUP)
    item = food(client, m)
    cook = butcher(client, db, m)
    lot = receive(client, sup, db, item).json()
    assert client.post(f"{LOTS}/{lot['id']}/status", headers=cook, json={"status": "discarded"}).status_code == 400
    assert client.post(f"{LOTS}/{lot['id']}/status", headers=cook, json={"status": "discarded", "note": "Packaging torn"}).status_code == 200
    assert client.post(f"{LOTS}/{lot['id']}/status", headers=cook, json={"status": "active"}).status_code == 403
    assert client.delete(f"{LOTS}/{lot['id']}", headers=m).status_code == 405
    assert db.scalar(select(Lot).where(Lot.id == lot["id"])) is not None
    assert db.scalar(select(AuditLog).where(AuditLog.action == "lot.status")) is not None


def test_a_trace_runs_back_to_the_supplier_and_forward_to_the_portions_and_exports_as_pdf(client, login, db, clock):
    m, sup = login(MGR), login(SUP)
    item = food(client, m)
    rule(client, m)
    cook = butcher(client, db, m)
    lot = receive(client, sup, db, item).json()
    child = client.post(f"{LOTS}/{lot['id']}/split", headers=cook, json={"parts": [part()]}).json()["lots"][0]
    grandchild = client.post(f"{LOTS}/{child['id']}/split", headers=cook, json={"parts": [part(description="100 g strips", count=48)]}).json()["lots"][0]
    assert grandchild["code"] == "B2610-884-1-1"
    forward = client.get(f"{LOTS}/{lot['id']}", headers=m).json()
    assert [x["code"] for x in forward["forward"]] == [child["code"], grandchild["code"]] and forward["back"] == []
    back = client.get(f"{LOTS}/{grandchild['id']}", headers=m).json()
    assert [x["code"] for x in back["back"]] == [lot["code"], child["code"]] and back["back"][0]["supplier_lot"] == "B2610-884"
    pdf = client.get(f"{LOTS}/{lot['id']}/trace/export", headers=m)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF") and "trace-B2610-884.pdf" in pdf.headers["content-disposition"]
    assert client.get(f"{LOTS}/{lot['id']}/trace/export", headers=login(STEWARD)).status_code == 403


def test_a_lot_is_only_visible_where_the_person_works(client, login, db, clock):
    m = login(MGR)
    item = food(client, m)
    lot = receive(client, login(SUP), db, item).json()
    assert client.get(f"{LOTS}/{lot['id']}", headers=login(SUP_RB)).status_code == 403
    assert [x["code"] for x in client.get(LOTS, headers=login(SUP_RB)).json()["items"]] == []
    assert [x["code"] for x in client.get(LOTS, headers=login(SUP)).json()["items"]] == [lot["code"]]
    assert client.get(f"{LOTS}/labels?ids={lot['id']}", headers=login(SUP_RB)).status_code == 403


def test_search_and_scanning_find_a_lot_by_code_and_say_when_it_may_not_be_used(client, login, db, clock):
    m, sup = login(MGR), login(SUP)
    item = food(client, m, "Salmon fillet", "seafood")
    lot = receive(client, sup, db, item, expiry_on="2026-03-03").json()
    chef = login(STEWARD)                                                # a steward records checks, so may look lots up
    assert [x["code"] for x in client.get(f"{LOTS}/search?q=salmon", headers=chef).json()] == [lot["code"]]
    assert [x["code"] for x in client.get(f"{LOTS}/search?q=b2610", headers=chef).json()] == [lot["code"]]
    found = client.get(f"{LOTS}/by-code/{lot['code'].lower()}", headers=chef).json()
    assert found["id"] == lot["id"] and found["blocked"] is None
    clock.advance(days=3)
    assert "past its use-by" in client.get(f"{LOTS}/by-code/{lot['code']}", headers=chef).json()["blocked"]
    assert client.get(f"{LOTS}/by-code/NOPE-1", headers=chef).status_code == 404


def test_labels_show_the_facts_and_come_as_pdf_or_zpl(client, login, db, clock):
    m, sup = login(MGR), login(SUP)
    item = food(client, m)
    rule(client, m)
    cook = butcher(client, db, m)
    supplier = client.post("/api/suppliers", headers=m, json={"name": "Al Wazzan Poultry"}).json()["id"]
    lot = receive(client, sup, db, item, supplier_id=supplier).json()
    child = client.post(f"{LOTS}/{lot['id']}/split", headers=cook, json={"parts": [part()]}).json()["lots"][0]
    pdf = client.get(f"{LOTS}/labels?ids={lot['id']},{child['id']}&copies=2", headers=sup)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF") and b"/Count 4" in pdf.content
    zpl = client.get(f"{LOTS}/labels?ids={child['id']}&fmt=zpl&dpi=300", headers=cook)
    text = zpl.text
    assert zpl.status_code == 200 and text.startswith("^XA") and "^PW886" in text and "^LL591" in text          # 75 x 50 mm at 300 dpi
    for needle in (child["code"], "Chicken breast", "Al Wazzan Poultry", "B2610-884", "Produced 27 Feb 2026", "Expiry 10 Mar 2026", "Portioned 02 Mar 2026 06:05",
                   "24 x 200 g breast portions, vacuum", "USE BY"):
        assert needle in text, needle
    assert "Received 02 Mar 2026 06:05" in client.get(f"{LOTS}/labels?ids={lot['id']}&fmt=zpl", headers=sup).text
    assert client.get(f"{LOTS}/labels?ids=abc", headers=sup).status_code == 400
    assert client.get(f"{LOTS}/labels?ids={lot['id']}", headers=login(STEWARD)).status_code == 403


def test_shelf_life_rules_and_food_items_are_managed_and_validated(client, login, db, clock):
    m, sup = login(MGR), login(SUP)
    assert client.put(f"{LOTS}/rules", headers=sup, json={"food_group": "poultry", "condition": "frozen", "hours": 100}).status_code == 403
    assert client.put(f"{LOTS}/rules", headers=m, json={"food_group": "poultry", "condition": "frozen", "hours": 0}).status_code == 422
    assert client.put(f"{LOTS}/rules", headers=m, json={"food_group": "bread", "condition": "frozen", "hours": 5}).status_code == 422
    rule(client, m, hours=72)
    rule(client, m, hours=96)                                            # saving again changes the rule instead of adding another
    listed = client.get(f"{LOTS}/rules", headers=sup).json()
    assert [(r["food_group"], r["condition"], r["hours"]) for r in listed["rules"]] == [("poultry", "vacuum_chilled", 96)]
    assert {g["key"] for g in listed["groups"]} >= {"poultry", "red_meat", "seafood"} and len(listed["conditions"]) == 5
    food(client, m, "Lamb leg", "red_meat")
    assert client.post(f"{LOTS}/food-items", headers=m, json={"name": "lamb LEG", "food_group": "red_meat"}).status_code == 409
    assert [i["name"] for i in client.get(f"{LOTS}/food-items", headers=sup).json()] == ["Lamb leg"]
    item_id = client.get(f"{LOTS}/food-items", headers=sup).json()[0]["id"]
    assert client.put(f"{LOTS}/food-items/{item_id}", headers=m, json={"active": False}).status_code == 200
    assert client.get(f"{LOTS}/food-items", headers=sup).json() == []
    assert receive(client, sup, db, item_id).status_code == 400          # an inactive item cannot be received


def point_with_lots(client, m, db, template="cooking"):
    point = make(client, m, db, template)
    body = {"stage": "Lots used", "parameter": "Core temperature", "unit": "C", "value_type": "number", "min_value": 75, "max_value": 100,
            "timing": "manual", "trace_lots": True}
    made = client.post(f"/api/equipment/{point['id']}/schedules", headers=m, json=body)
    assert made.status_code == 201 and made.json()["trace_lots"] is True
    return point, made.json()


def test_a_check_that_traces_lots_needs_them_and_links_them_to_the_record(client, login, db, clock):
    m, sup, steward = login(MGR), login(SUP), login(STEWARD)
    item = food(client, m)
    rule(client, m)
    cook = butcher(client, db, m)
    lot = receive(client, sup, db, item).json()
    child = client.post(f"{LOTS}/{lot['id']}/split", headers=cook, json={"parts": [part()]}).json()["lots"][0]
    point, check = point_with_lots(client, m, db)
    record = {"equipment_id": point["id"], "schedule_id": check["id"], "value": 82}
    assert client.post("/api/monitoring/readings", headers=steward, json=record).status_code == 400            # no lot named
    assert client.post("/api/monitoring/readings", headers=steward, json={**record, "lot_ids": [999]}).status_code == 400
    done = client.post("/api/monitoring/readings", headers=steward, json={**record, "lot_ids": [child["id"]]})
    assert done.status_code == 201 and [(x["id"], x["code"]) for x in done.json()["lots"]] == [(child["id"], child["code"])] and done.json()["reference"] == child["code"]
    listed = client.get(f"/api/monitoring/readings?equipment_id={point['id']}", headers=m).json()["items"]
    assert listed[0]["lots"][0]["code"] == child["code"]
    assert listed[0]["lots"][0]["item"] == "Chicken breast" and listed[0]["lots"][0]["pack"] == child["pack_description"]
    from_parent = client.get(f"{LOTS}/{lot['id']}", headers=m).json()
    assert [(u["lot_code"], u["stage"], u["passed"]) for u in from_parent["uses_forward"]] == [(child["code"], "Lots used", True)]   # the cook record is found from the delivery
    from_child = client.get(f"{LOTS}/{child['id']}", headers=m).json()
    assert from_child["uses_forward"][0]["equipment"] == point["name"] and from_child["uses_back"] == []
    assert client.get(f"{LOTS}/{lot['id']}/trace/export", headers=m).content.startswith(b"%PDF")


def test_a_check_cannot_use_a_lot_that_is_on_hold_discarded_or_out_of_date(client, login, db, clock):
    m, sup, steward = login(MGR), login(SUP), login(STEWARD)
    item = food(client, m)
    point, check = point_with_lots(client, m, db)
    lot = receive(client, sup, db, item, expiry_on="2026-03-04").json()
    record = {"equipment_id": point["id"], "schedule_id": check["id"], "value": 82, "lot_ids": [lot["id"]]}
    client.post(f"{LOTS}/{lot['id']}/status", headers=m, json={"status": "on_hold", "note": "Recall"})
    blocked = client.post("/api/monitoring/readings", headers=steward, json=record)
    assert blocked.status_code == 409 and "on hold" in blocked.json()["detail"]
    client.post(f"{LOTS}/{lot['id']}/status", headers=m, json={"status": "active"})
    assert client.post("/api/monitoring/readings", headers=steward, json=record).status_code == 201
    clock.advance(days=4)
    assert "past its use-by" in client.post("/api/monitoring/readings", headers=steward, json={**record, "value": 83}).json()["detail"]


def test_the_lots_of_a_time_in_carry_over_to_the_time_out(client, login, db, clock):
    m, sup, steward = login(MGR), login(SUP), login(STEWARD)
    item = food(client, m)
    lot = receive(client, sup, db, item).json()
    point = make(client, m, db, "defrosting")
    starts = [c for c in point["schedules"] if c["phase"] == "start"]
    started = client.post("/api/monitoring/readings/batch", headers=steward, json={"equipment_id": point["id"], "readings": [
        {"schedule_id": c["id"], "value": 3, "lot_ids": [lot["id"]]} for c in starts]})
    assert started.status_code == 201 and all([(x["id"], x["code"]) for x in r["lots"]] == [(lot["id"], lot["code"])] and r["reference"] == lot["code"] for r in started.json())
    done = finish(client, steward, point, started.json()[0]["id"])                 # the time out names no lot
    assert done.status_code == 201 and all([(x["id"], x["code"]) for x in r["lots"]] == [(lot["id"], lot["code"])] for r in done.json())
    uses = client.get(f"{LOTS}/{lot['id']}", headers=m).json()["uses_forward"]
    assert len(uses) == len(starts) + len(done.json())


def test_a_retest_keeps_the_lots_of_the_failed_reading_and_receiving_lists_suppliers(client, login, db, clock):
    m, sup, steward = login(MGR), login(SUP), login(STEWARD)
    item = food(client, m)
    lot = receive(client, sup, db, item).json()
    point, check = point_with_lots(client, m, db)
    failed = client.post("/api/monitoring/readings", headers=steward, json={"equipment_id": point["id"], "schedule_id": check["id"], "value": 40,
                                                                         "lot_ids": [lot["id"]], "corrective_action": "Cooked it longer"})
    assert failed.status_code == 201 and failed.json()["passed"] is False
    retest = client.post("/api/monitoring/readings", headers=steward, json={"equipment_id": point["id"], "schedule_id": check["id"], "value": 80,
                                                                          "retest_of_id": failed.json()["id"]})
    assert retest.status_code == 201 and [(x["id"], x["code"]) for x in retest.json()["lots"]] == [(lot["id"], lot["code"])]
    client.post("/api/suppliers", headers=m, json={"name": "Al Wazzan Poultry"})
    assert "Al Wazzan Poultry" in [s["name"] for s in client.get(f"{LOTS}/suppliers", headers=sup).json()]
    assert client.get(f"{LOTS}/suppliers", headers=steward).status_code == 403


def test_a_frozen_lot_is_thawed_once_and_its_use_by_follows_the_thawed_rule(client, login, db, clock):
    m, sup = login(MGR), login(SUP)
    item = food(client, m)
    cook = butcher(client, db, m)
    lot = receive(client, sup, db, item, condition="frozen", temp_c=-18, expiry_on="2026-03-30").json()
    thaw = f"{LOTS}/{lot['id']}/thaw"
    blocked = client.post(thaw, headers=cook)
    assert blocked.status_code == 409 and "shelf-life rule" in blocked.json()["detail"]
    assert client.post(thaw, headers=sup).status_code == 403                    # a supervisor does not thaw
    rule(client, m, condition="thawed", hours=48)
    done = client.post(thaw, headers=cook)
    assert done.status_code == 200
    thawed = done.json()
    assert (thawed["condition"], thawed["use_by"], thawed["thawed_at"]) == ("thawed", "2026-03-04T02:05:00Z", "2026-03-02T02:05:00Z")
    again = client.post(thaw, headers=cook)
    assert again.status_code == 409 and "already thawed" in again.json()["detail"]
    chilled = receive(client, sup, db, item).json()
    assert "Only a frozen lot" in client.post(f"{LOTS}/{chilled['id']}/thaw", headers=cook).json()["detail"]
    zpl = client.get(f"{LOTS}/labels?ids={lot['id']}&fmt=zpl", headers=cook).text
    assert "Thawed 02 Mar 2026 06:05" in zpl and "Thawed" in zpl and "USE BY 04 Mar 2026 06:05" in zpl
    detail = client.get(f"{LOTS}/{lot['id']}", headers=m).json()
    assert any(e["kind"] == "thaw" and "Thawed; use by" in e["detail"] for e in detail["events"])
    assert db.scalar(select(AuditLog).where(AuditLog.action == "lot.thaw")) is not None


def test_thawing_never_pushes_the_use_by_past_the_suppliers_expiry(client, login, db, clock):
    m, sup = login(MGR), login(SUP)
    item = food(client, m)
    cook = butcher(client, db, m)
    rule(client, m, condition="thawed", hours=500)
    lot = receive(client, sup, db, item, condition="frozen", temp_c=-18, expiry_on="2026-03-03").json()
    assert client.post(f"{LOTS}/{lot['id']}/thaw", headers=cook).json()["use_by"] == "2026-03-03T20:00:00Z"


def test_thawed_food_can_only_be_portioned_as_thawed_and_frozen_food_must_be_thawed_first(client, login, db, clock):
    m, sup = login(MGR), login(SUP)
    item = food(client, m)
    cook = butcher(client, db, m)
    rule(client, m, condition="thawed", hours=48)
    rule(client, m, condition="vacuum_chilled", hours=96)
    lot = receive(client, sup, db, item, condition="frozen", temp_c=-18, expiry_on="2026-04-30").json()
    too_soon = client.post(f"{LOTS}/{lot['id']}/split", headers=cook, json={"parts": [part(condition="thawed")]})
    assert too_soon.status_code == 409 and "Thaw the lot first" in too_soon.json()["detail"]
    client.post(f"{LOTS}/{lot['id']}/thaw", headers=cook)
    refrozen = client.post(f"{LOTS}/{lot['id']}/split", headers=cook, json={"parts": [part(condition="vacuum_chilled")]})
    assert refrozen.status_code == 409 and "cannot be frozen or re-stored" in refrozen.json()["detail"]
    made = client.post(f"{LOTS}/{lot['id']}/split", headers=cook, json={"parts": [part(condition="thawed")]})
    assert made.status_code == 201
    child = made.json()["lots"][0]
    assert child["condition"] == "thawed" and child["use_by"] == made.json()["parent"]["use_by"]


def test_food_already_past_its_expiry_is_refused_at_receiving(client, login, db, clock):
    m, sup = login(MGR), login(SUP)
    item = food(client, m)
    refused = receive(client, sup, db, item, expiry_on="2026-03-01")
    assert refused.status_code == 400 and "past its expiry date" in refused.json()["detail"]
    assert db.scalar(select(Lot.id)) is None
    assert receive(client, sup, db, item, expiry_on="2026-03-02").status_code == 201


def test_a_warm_delivery_is_held_on_arrival_and_only_a_manager_releases_it(client, login, db, clock):
    m, sup = login(MGR), login(SUP)
    item = food(client, m)
    warm = receive(client, sup, db, item, temp_c=8).json()
    assert warm["status"] == "on_hold"
    event = db.scalar(select(LotEvent).where(LotEvent.lot_id == warm["id"]))
    assert event.detail == "Held on arrival: 8 C is above the 5 C limit for chilled, raw food"
    assert receive(client, sup, db, item, temp_c=5).json()["status"] == "active"
    assert receive(client, sup, db, item, temp_c=None).json()["status"] == "active"
    assert receive(client, sup, db, item, condition="frozen", temp_c=-10).json()["status"] == "on_hold"
    assert receive(client, sup, db, item, condition="frozen", temp_c=-18).json()["status"] == "active"
    assert client.post(f"{LOTS}/{warm['id']}/status", headers=sup, json={"status": "active"}).status_code == 403
    assert client.post(f"{LOTS}/{warm['id']}/status", headers=m, json={"status": "active"}).json()["status"] == "active"


def test_a_delivery_cannot_be_received_without_a_known_supplier(client, login, db, clock):
    m, sup = login(MGR), login(SUP)
    item = food(client, m)
    body = {"food_item_id": item, "location_id": loc_id(db, "MK"), "condition": "chilled_raw", "supplier_lot": "B2610-884"}
    missing = client.post(LOTS, headers=sup, json=body)
    assert missing.status_code == 422 and missing.json()["detail"][0]["loc"] == ["body", "supplier_id"]
    assert client.post(LOTS, headers=sup, json={**body, "supplier_id": 9999}).json()["detail"] == "Unknown supplier"
    assert db.scalar(select(Lot.id)) is None
    assert client.post(LOTS, headers=sup, json={**body, "supplier_id": a_supplier(db)}).status_code == 201


def test_a_delivery_cannot_be_received_without_the_suppliers_lot_number(client, login, db, clock):
    m, sup = login(MGR), login(SUP)
    item = food(client, m)
    body = {"food_item_id": item, "supplier_id": a_supplier(db), "location_id": loc_id(db, "MK"), "condition": "chilled_raw"}
    for lot_number in (None, "", "   "):
        refused = client.post(LOTS, headers=sup, json={**body, "supplier_lot": lot_number})
        assert refused.status_code == 422 and refused.json()["detail"][0]["loc"] == ["body", "supplier_lot"]
    assert client.post(LOTS, headers=sup, json=body).status_code == 422
    assert db.scalar(select(Lot.id)) is None
    assert client.post(LOTS, headers=sup, json={**body, "supplier_lot": "  B2610   884 "}).json()["supplier_lot"] == "B2610 884"


def test_a_manager_sets_the_arrival_temperature_limits_and_they_apply_to_the_next_delivery(client, login, db, clock):
    m, sup = login(MGR), login(SUP)
    item = food(client, m)
    assert client.get(f"{LOTS}/rules", headers=sup).json()["cold_chain"] == {"chilled_raw": 5.0, "vacuum_chilled": 5.0, "frozen": -12.0}
    assert receive(client, sup, db, item, temp_c=7).json()["status"] == "on_hold"
    assert client.put(f"{LOTS}/cold-chain", headers=sup, json={"condition": "chilled_raw", "max_c": 8}).status_code == 403
    saved = client.put(f"{LOTS}/cold-chain", headers=m, json={"condition": "chilled_raw", "max_c": 8})
    assert saved.json()["cold_chain"] == {"chilled_raw": 8.0, "vacuum_chilled": 5.0, "frozen": -12.0}
    assert receive(client, sup, db, item, temp_c=7).json()["status"] == "active"
    held = receive(client, sup, db, item, temp_c=8.5).json()
    assert held["status"] == "on_hold"
    assert db.scalar(select(LotEvent.detail).where(LotEvent.lot_id == held["id"])) == "Held on arrival: 8.5 C is above the 8 C limit for chilled, raw food"
    assert receive(client, sup, db, item, condition="vacuum_chilled", temp_c=7).json()["status"] == "on_hold"
    assert client.put(f"{LOTS}/cold-chain", headers=m, json={"condition": "frozen", "max_c": -25}).status_code == 200
    assert receive(client, sup, db, item, condition="frozen", temp_c=-18).json()["status"] == "on_hold"
    assert client.put(f"{LOTS}/cold-chain", headers=m, json={"condition": "frozen", "max_c": 99}).status_code == 422
    assert client.put(f"{LOTS}/cold-chain", headers=m, json={"condition": "thawed", "max_c": 4}).status_code == 422
    audit = db.scalar(select(AuditLog).where(AuditLog.action == "lot.cold_chain_save").order_by(AuditLog.id))
    assert audit.before == {"chilled_raw": 5.0} and audit.after == {"chilled_raw": 8.0}


def test_a_lot_shows_what_is_left_to_portion_in_comparable_units(client, login, db, clock):
    m, sup, cook = login(MGR), login(SUP), None
    item = food(client, m)
    rule(client, m)
    cook = butcher(client, db, m)
    lot = receive(client, sup, db, item, qty=20, unit="kg").json()
    assert client.get(f"{LOTS}/{lot['id']}", headers=m).json()["balance"] == {"qty": 20.0, "unit": "kg", "portioned": 0.0, "waste": 0.0, "left": 20.0, "unmeasured": 0}
    cut = {"description": "200 g breast portions", "count": 24, "condition": "vacuum_chilled"}
    assert client.post(f"{LOTS}/{lot['id']}/split", headers=cook, json={"parts": [{**cut, "qty": 4.8, "unit": "kg"}]}).status_code == 201
    assert client.get(f"{LOTS}/{lot['id']}", headers=m).json()["balance"]["left"] == 15.2
    assert client.post(f"{LOTS}/{lot['id']}/split", headers=cook, json={"parts": [{**cut, "qty": 500, "unit": "G"}]}).status_code == 201
    assert client.get(f"{LOTS}/{lot['id']}", headers=m).json()["balance"] == {"qty": 20.0, "unit": "kg", "portioned": 5.3, "waste": 0.0, "left": 14.7, "unmeasured": 0}
    assert client.post(f"{LOTS}/{lot['id']}/split", headers=cook, json={"parts": [{**cut, "qty": 3, "unit": "trays"}, cut]}).status_code == 201
    assert client.get(f"{LOTS}/{lot['id']}", headers=m).json()["balance"] == {"qty": 20.0, "unit": "kg", "portioned": 5.3, "waste": 0.0, "left": 14.7, "unmeasured": 2}


def test_a_lot_without_a_quantity_or_unit_has_no_balance(client, login, db, clock):
    m, sup = login(MGR), login(SUP)
    item = food(client, m)
    assert client.get(f"{LOTS}/{receive(client, sup, db, item).json()['id']}", headers=m).json()["balance"] is None
    assert client.get(f"{LOTS}/{receive(client, sup, db, item, qty=5).json()['id']}", headers=m).json()["balance"] is None


def test_a_lot_timeline_follows_it_through_thaw_defrost_cooling_and_reheating(client, login, db, clock):
    m, sup, steward = login(MGR), login(SUP), login(STEWARD)
    item = food(client, m)
    rule(client, m, condition="thawed", hours=48)
    cook = butcher(client, db, m)
    lot = receive(client, sup, db, item, condition="frozen", temp_c=-18, expiry_on="2026-03-30").json()
    clock.advance(hours=1)
    assert client.post(f"{LOTS}/{lot['id']}/thaw", headers=cook).status_code == 200

    def record_in(point, value):
        return client.post("/api/monitoring/readings/batch", headers=steward, json={"equipment_id": point["id"], "readings": [
            {"schedule_id": c["id"], "value": value, "lot_ids": [lot["id"]]} for c in checks(point, "start")]}).json()

    clock.advance(hours=1)
    defrost = make(client, m, db, "defrosting")
    assert finish(client, steward, defrost, record_in(defrost, 3)[0]["id"]).status_code == 201
    clock.advance(hours=1)
    cooling = make(client, m, db, "cooling")
    assert finish(client, steward, cooling, record_in(cooling, 80)[0]["id"]).status_code == 201
    clock.advance(hours=3)
    reheating = make(client, m, db, "reheating")
    done = client.post("/api/monitoring/readings", headers=steward, json={"equipment_id": reheating["id"], "schedule_id": reheating["schedules"][0]["id"], "value": 80, "lot_ids": [lot["id"]]})
    assert done.status_code == 201
    line = client.get(f"{LOTS}/{lot['id']}", headers=m).json()["timeline"]
    assert [i["title"] for i in line] == ["Received", "Thawed", "Time in", "Time out", "Time out", "Time in", "Time out", "Core temperature after reheating"]
    assert [i["at"] for i in line] == sorted(i["at"] for i in line)
    assert {i["lot_code"] for i in line} == {lot["code"]} and {i["tone"] for i in line[2:]} == {"ok"}
    assert [i["detail"].split(":")[0] for i in line[2:]] == [defrost["name"]] * 3 + [cooling["name"]] * 2 + [reheating["name"]]
    clock.advance(hours=1)
    child = client.post(f"{LOTS}/{lot['id']}/split", headers=cook, json={"parts": [part(condition="thawed")]}).json()["lots"][0]
    from_child = [i["title"] for i in client.get(f"{LOTS}/{child['id']}", headers=m).json()["timeline"]]
    assert from_child[:2] == ["Received", "Thawed"] and from_child[-2:] == ["Split", "Portioned"] and len(from_child) == 10


def test_a_cut_takes_a_size_and_a_count_and_works_out_its_total_and_the_waste(client, login, db, clock):
    m, sup = login(MGR), login(SUP)
    item = food(client, m)
    rule(client, m)
    cook = butcher(client, db, m)
    lot = receive(client, sup, db, item, qty=20, unit="kg").json()
    cut = {"description": "Chicken breast portions", "count": 24, "size": 200, "unit": "g", "condition": "vacuum_chilled", "waste": 600}
    made = client.post(f"{LOTS}/{lot['id']}/split", headers=cook, json={"parts": [cut]})
    assert made.status_code == 201
    child = made.json()["lots"][0]
    assert (child["qty"], child["unit"], child["waste_qty"], child["pack_count"]) == (4800.0, "g", 600.0, 24)
    assert child["pack_description"] == "200 g Chicken breast portions"
    assert client.get(f"{LOTS}/{lot['id']}", headers=m).json()["balance"] == {"qty": 20.0, "unit": "kg", "portioned": 4.8, "waste": 0.6, "left": 14.6, "unmeasured": 0}
    timeline = client.get(f"{LOTS}/{child['id']}", headers=m).json()["timeline"]
    assert next(i for i in timeline if i["title"] == "Portioned")["detail"] == "24 x 200 g Chicken breast portions, total 4800 g, waste 600 g"
    for bad in ({"unit": None}, {"size": 0}, {"waste": -1}):
        refused = client.post(f"{LOTS}/{lot['id']}/split", headers=cook, json={"parts": [{**cut, **bad}]})
        assert refused.status_code == 422, bad
    assert client.post(f"{LOTS}/{lot['id']}/split", headers=cook, json={"parts": [{"description": "Whole breasts", "count": 2, "condition": "vacuum_chilled"}]}).status_code == 201


def test_the_supplier_lot_is_the_lot_code_and_a_repeat_delivery_gets_a_letter(client, login, db, clock):
    m, sup = login(MGR), login(SUP)
    item = food(client, m)
    rule(client, m)
    cook = butcher(client, db, m)
    first = receive(client, sup, db, item, supplier_lot="b2610  884").json()
    assert (first["code"], first["supplier_lot"]) == ("B2610-884", "b2610 884")
    again = receive(client, sup, db, item, supplier_lot="B2610-884").json()
    third = receive(client, sup, db, item, supplier_lot="B2610-884").json()
    assert (again["code"], third["code"]) == ("B2610-884-B", "B2610-884-C")
    child = client.post(f"{LOTS}/{again['id']}/split", headers=cook, json={"parts": [part()]}).json()["lots"][0]
    assert child["code"] == "B2610-884-B-1" and child["supplier_lot"] == "B2610-884"
    assert receive(client, sup, db, item, supplier_lot="Other 77").json()["code"] == "OTHER-77"


def test_a_supplier_lot_may_only_use_letters_digits_and_a_few_marks(client, login, db, clock):
    m, sup = login(MGR), login(SUP)
    item = food(client, m)
    for bad in ("B26^10", "B26~10", "B26;10", "-B2610", "X" * 31):
        refused = receive(client, sup, db, item, supplier_lot=bad)
        assert refused.status_code == 422 and refused.json()["detail"][0]["loc"] == ["body", "supplier_lot"], bad
    assert db.scalar(select(Lot.id)) is None
    assert receive(client, sup, db, item, supplier_lot="AB/12.3_4-5").json()["code"] == "AB/12.3_4-5"


def test_a_code_with_a_slash_can_be_scanned_and_typed_in_any_case(client, login, db, clock):
    from urllib.parse import quote
    m, sup = login(MGR), login(SUP)
    item = food(client, m)
    lot = receive(client, sup, db, item, supplier_lot="AB/12").json()
    for typed in ("AB/12", "ab/12", " ab/12 "):
        found = client.get(f"{LOTS}/by-code/{quote(typed, safe='')}", headers=m)
        assert found.status_code == 200 and found.json()["id"] == lot["id"], typed
    assert client.get(f"{LOTS}/by-code/NOPE", headers=m).status_code == 404


def test_the_lot_list_filters_by_food_group_and_supplier_and_a_viewer_can_list_suppliers(client, login, db, clock):
    m, sup = login(MGR), login(SUP)
    chicken, salmon = food(client, m), food(client, m, "Salmon fillet", "seafood")
    other = client.post("/api/suppliers", headers=m, json={"name": "Gulf Seafood"}).json()["id"]
    receive(client, sup, db, chicken, supplier_lot="B1")
    receive(client, sup, db, salmon, supplier_lot="S1", supplier_id=other)

    def codes(**params):
        query = "&".join(f"{k}={v}" for k, v in params.items())
        return sorted(x["code"] for x in client.get(f"{LOTS}?{query}", headers=m).json()["items"])

    assert codes() == ["B1", "S1"] and codes(food_group="seafood") == ["S1"] and codes(supplier_id=other) == ["S1"]
    assert codes(food_group="poultry", supplier_id=other) == []
    cook = butcher(client, db, m)
    names = [s["name"] for s in client.get(f"{LOTS}/suppliers", headers=cook).json()]
    assert "Gulf Seafood" in names
    assert client.get(f"{LOTS}/suppliers", headers=login(STEWARD)).status_code == 403


def test_a_food_item_is_deleted_unless_a_lot_was_received_of_it(client, login, db, clock):
    m, sup = login(MGR), login(SUP)
    spare = food(client, m, name="Spare food")
    assert client.delete(f"{LOTS}/food-items/{spare}", headers=sup).status_code == 403
    assert client.delete(f"{LOTS}/food-items/{spare}", headers=m).json() == {"deleted": spare}
    assert all(i["id"] != spare for i in client.get(f"{LOTS}/food-items?include_inactive=true", headers=m).json())
    assert db.scalars(select(AuditLog).where(AuditLog.action == "lot.food_item_delete")).one().before == {"name": "Spare food", "food_group": "poultry"}
    used = food(client, m, name="Chicken thigh")
    assert receive(client, sup, db, used).status_code == 201
    r = client.delete(f"{LOTS}/food-items/{used}", headers=m)
    assert r.status_code == 409 and "food lots" in r.json()["detail"] and "make it inactive instead" in r.json()["detail"]
    assert client.delete(f"{LOTS}/food-items/99999", headers=m).status_code == 404
