from .test_monitoring import MGR, STEWARD, mk_stage, record

CHECK = {"stage": "Probe check", "timing": "manual", "value_type": "yes_no"}


def new_point(client, h):
    location_id = client.get("/api/equipment", headers=h).json()[0]["location_id"]
    body = {"code": "TST-1", "name": "Test point", "kind": "freezer", "location_id": location_id}
    point = client.post("/api/equipment", json=body, headers=h)
    assert point.status_code == 201, point.text
    point = point.json()
    check = client.post(f"/api/equipment/{point['id']}/schedules", json=CHECK, headers=h)
    assert check.status_code == 201, check.text
    return point, check.json()


def test_unused_check_and_point_can_be_deleted(client, login):
    h = login(MGR)
    point, check = new_point(client, h)
    assert client.delete(f"/api/equipment/schedules/{check['id']}", headers=h).status_code == 200
    assert client.delete(f"/api/equipment/{point['id']}", headers=h).status_code == 200
    assert all(e["id"] != point["id"] for e in client.get("/api/equipment", headers=h).json())


def test_delete_needs_the_manage_permission(client, login):
    point, check = new_point(client, login(MGR))
    steward = login(STEWARD)
    assert client.delete(f"/api/equipment/schedules/{check['id']}", headers=steward).status_code == 403
    assert client.delete(f"/api/equipment/{point['id']}", headers=steward).status_code == 403


def test_check_and_point_with_readings_cannot_be_deleted(client, login, clock):
    h = login(MGR)
    eq, sched = mk_stage(client, h)
    assert record(client, h, eq, sched, 60.0).status_code == 201
    r = client.delete(f"/api/equipment/schedules/{sched['id']}", headers=h)
    assert r.status_code == 409 and "inactive" in r.json()["detail"]
    assert client.delete(f"/api/equipment/{eq['id']}", headers=h).status_code == 409
    ids = [e["id"] for e in client.get("/api/equipment", headers=h).json()]
    assert eq["id"] in ids


def test_inactive_check_is_not_recorded_and_editing_keeps_it_inactive(client, login, clock):
    h = login(MGR)
    eq, sched = mk_stage(client, h)
    assert client.put(f"/api/equipment/schedules/{sched['id']}/active", json={"active": False}, headers=h).json()["active"] is False
    assert record(client, h, eq, sched, 60.0).status_code == 400
    edit = {k: sched[k] for k in ("stage", "parameter", "unit", "value_type", "timing", "min_value", "max_value")}
    assert client.put(f"/api/equipment/schedules/{sched['id']}", json=edit, headers=h).json()["active"] is False
    assert client.put(f"/api/equipment/schedules/{sched['id']}/active", json={"active": True}, headers=h).json()["active"] is True
    assert record(client, h, eq, sched, 60.0).status_code == 201
