from .helpers import MGR, SUP
from .test_traceability import LOTS, butcher, food, part, receive, rule


def names(client, h, **params):
    return client.get(f"{LOTS}/portion-names", headers=h, params=params).json()


def test_a_custom_portion_name_is_saved_to_the_list_once(client, login, db, clock):
    m, sup = login(MGR), login(SUP)
    item = food(client, m)
    rule(client, m)
    cook = butcher(client, db, m)
    lot = receive(client, sup, db, item).json()
    for description in ("Breast portions", "breast PORTIONS"):
        assert client.post(f"{LOTS}/{lot['id']}/split", headers=cook, json={"parts": [part(description=description, count=2)]}).status_code == 201
    saved = names(client, m)
    assert [(n["name"], n["food_item_id"]) for n in saved] == [("Breast portions", item)]


def test_managers_keep_the_list_and_others_only_read_it(client, login, db):
    m, sup = login(MGR), login(SUP)
    item = food(client, m)
    made = client.post(f"{LOTS}/portion-names", headers=m, json={"name": "Thigh strips", "food_item_id": item})
    assert made.status_code == 201 and made.json()["food_item"] == "Chicken breast"
    assert client.post(f"{LOTS}/portion-names", headers=m, json={"name": "thigh STRIPS"}).status_code == 409
    assert client.post(f"{LOTS}/portion-names", headers=sup, json={"name": "Wings"}).status_code == 403
    assert [n["name"] for n in names(client, sup)] == ["Thigh strips"]
    pid = made.json()["id"]
    assert client.put(f"{LOTS}/portion-names/{pid}", headers=m, json={"active": False}).status_code == 200
    assert names(client, m) == [] and len(names(client, m, include_inactive=True)) == 1
    assert client.post(f"{LOTS}/portion-names", headers=m, json={"name": "Wings", "food_item_id": 9999}).status_code == 400
    assert client.delete(f"{LOTS}/portion-names/{pid}", headers=sup).status_code == 403
    assert client.delete(f"{LOTS}/portion-names/{pid}", headers=m).status_code == 200
    assert names(client, m, include_inactive=True) == []


def test_lot_search_finds_a_lot_by_its_portion_name_and_shows_the_supplier_batch(client, login, db, clock):
    m, sup = login(MGR), login(SUP)
    item = food(client, m)
    rule(client, m)
    cook = butcher(client, db, m)
    lot = receive(client, sup, db, item).json()
    client.post(f"{LOTS}/{lot['id']}/split", headers=cook, json={"parts": [part(description="Satay skewers", count=3)]})
    found = client.get(f"{LOTS}/search", headers=cook, params={"q": "satay"}).json()
    assert len(found) == 1 and found[0]["pack"] == "Satay skewers" and found[0]["supplier_lot"] == "B2610-884"


def test_the_lots_list_nests_each_lots_portions_under_the_delivery_and_shows_what_is_left(client, login, db, clock):
    m, sup = login(MGR), login(SUP)
    item = food(client, m)
    rule(client, m)
    cook = butcher(client, db, m)
    lot = receive(client, sup, db, item, qty=6.7, unit="kg").json()
    other = receive(client, sup, db, item, supplier_lot="B-OTHER").json()
    cuts = [part(description="Steak portions", count=10, size=200, unit="g"), part(description="Trim", count=1, size=1500, unit="g")]
    assert client.post(f"{LOTS}/{lot['id']}/split", headers=cook, json={"parts": cuts}).status_code == 201
    flat = client.get(LOTS, headers=m).json()
    assert flat["total"] == 4
    grouped = client.get(LOTS, headers=m, params={"grouped": True}).json()
    assert grouped["total"] == 2
    family = next(i for i in grouped["items"] if i["id"] == lot["id"])
    assert [c["pack_description"] for c in family["children"]] == ["200 g Steak portions", "1500 g Trim"]
    assert [c["code"] for c in family["children"]] == [f"{lot['code']}-1", f"{lot['code']}-2"]
    assert family["balance"] == {"qty": 6.7, "unit": "kg", "portioned": 3.5, "waste": 0.0, "left": 3.2, "unmeasured": 0}
    assert next(i for i in grouped["items"] if i["id"] == other["id"])["children"] == []
    for query in ("steak", lot["code"] + "-2"):
        found = client.get(LOTS, headers=m, params={"grouped": True, "q": query}).json()
        assert [i["id"] for i in found["items"]] == [lot["id"]] and len(found["items"][0]["children"]) == 2



def _portion_lot(client, login, db, clock):
    m, sup = login(MGR), login(SUP)
    item = food(client, m)
    rule(client, m)
    cook = butcher(client, db, m)
    lot = receive(client, sup, db, item, qty=6.7, unit="kg").json()
    child = client.post(f"{LOTS}/{lot['id']}/split", headers=cook, json={"parts": [part(description="Tenderloin steaks", count=13, size=200, unit="g")]}).json()["lots"][0]
    return lot, child, cook


def test_a_container_label_gives_the_count_and_total_and_a_pack_label_only_the_weight(client, login, db, clock):
    lot, child, cook = _portion_lot(client, login, db, clock)
    container = client.get(f"{LOTS}/labels?ids={child['id']}&fmt=zpl", headers=cook).text
    pack = client.get(f"{LOTS}/labels?ids={child['id']}&fmt=zpl&style=pack", headers=cook).text
    assert "13 x 200 g Tenderloin steaks, 2.6 kg in all" in container and container.count("^XA") == 1
    assert "200 g Tenderloin steaks" in pack and "13 x" not in pack and "in all" not in pack and "Pack " not in pack
    assert pack.count("^XA") == 13 and child["code"] in pack


def test_pack_labels_are_one_per_pack_times_the_copies_and_a_delivery_still_gets_one(client, login, db, clock):
    lot, child, cook = _portion_lot(client, login, db, clock)
    twice = client.get(f"{LOTS}/labels?ids={child['id']}&fmt=zpl&style=pack&copies=2", headers=cook).text
    assert twice.count("^XA") == 26
    delivery = client.get(f"{LOTS}/labels?ids={lot['id']}&fmt=zpl&style=pack", headers=login(SUP)).text
    assert delivery.count("^XA") == 1 and "6.7 kg" in delivery
    too_many = client.get(f"{LOTS}/labels?ids={child['id']}&fmt=zpl&style=pack&copies=50", headers=cook)
    assert too_many.status_code == 400 and "At most 200 labels" in too_many.json()["detail"]
