from sqlalchemy import select

from app.models import Equipment, Location, ScanEvent
from app.services.scan import make_token

MGR = "manager@example.test"
STEWARD = "steward.mk@example.test"
BASE = "https://plato.example.com"


def point_and_check(client, h, code="DW-MK-1", stage="wash"):
    eq = next(e for e in client.get("/api/monitoring/equipment", headers=h).json() if e["code"] == code)
    return eq, next(s for s in eq["schedules"] if s["stage"] == stage)


def record(client, h, eq, sched):
    return client.post("/api/monitoring/readings", json={"equipment_id": eq["id"], "schedule_id": sched["id"], "value": 60.0}, headers=h)


def require(client, login, key):
    assert client.put("/api/settings", json={"values": {key: 1}}, headers=login(MGR)).status_code == 200


def test_scanning_a_code_names_the_place_and_is_logged(client, login, db):
    h = login(STEWARD)
    eq, _ = point_and_check(client, h)
    r = client.post("/api/scan", json={"token": make_token("equipment", eq["id"])}, headers=h)
    assert r.status_code == 200
    assert r.json()["name"] == eq["name"] and r.json()["location_id"] == eq["location_id"]
    assert db.scalar(select(ScanEvent.target_id)) == eq["id"]


def test_a_forged_or_foreign_code_is_refused(client, login):
    h = login(STEWARD)
    eq, _ = point_and_check(client, h)
    forged = f"e{eq['id']}.{'0' * 20}"
    assert client.post("/api/scan", json={"token": forged}, headers=h).status_code == 400
    assert client.post("/api/scan", json={"token": "hello"}, headers=h).status_code == 400


def test_a_place_outside_the_users_locations_cannot_be_scanned(client, login, db):
    h = login(STEWARD)
    other = db.scalar(select(Equipment).join(Location, Equipment.location_id == Location.id).where(Location.code != "MK"))
    assert client.post("/api/scan", json={"token": make_token("equipment", other.id)}, headers=h).status_code == 403


def test_recording_a_check_needs_a_scan_only_when_required(client, login, clock):
    h = login(STEWARD)
    eq, sched = point_and_check(client, h)
    require(client, login, "scan.monitoring_required")
    blocked = record(client, h, eq, sched)
    assert blocked.status_code == 403 and "Scan the QR code" in blocked.json()["detail"]
    client.post("/api/scan", json={"token": make_token("equipment", eq["id"])}, headers=h)
    assert record(client, h, eq, sched).status_code == 201


def test_a_scan_of_one_point_does_not_cover_another_and_expires(client, login, clock):
    h = login(STEWARD)
    eq, sched = point_and_check(client, h)
    require(client, login, "scan.monitoring_required")
    other = next(e for e in client.get("/api/monitoring/equipment", headers=h).json() if e["id"] != eq["id"])
    client.post("/api/scan", json={"token": make_token("equipment", other["id"])}, headers=h)
    assert record(client, h, eq, sched).status_code == 403
    client.post("/api/scan", json={"token": make_token("equipment", eq["id"])}, headers=h)
    clock.advance(minutes=31)
    assert record(client, h, eq, sched).status_code == 403


def test_completing_a_checklist_task_needs_a_scan_of_its_location(client, login, db, clock):
    h = login(STEWARD)
    require(client, login, "scan.checklists_required")
    location_id = db.scalar(select(Location.id).where(Location.code == "MK"))
    assert client.post("/api/checklists/generate", json={"location_id": location_id}, headers=login(MGR)).status_code == 200
    task = next(i for i in client.get("/api/checklists/instances?size=200", headers=h).json()["items"] if not i["requires_photo"] and not i["requires_reading"])
    path = f"/api/checklists/instances/{task['id']}/complete"
    blocked = client.post(path, json={}, headers=h)
    assert blocked.status_code == 403 and "Scan the QR code" in blocked.json()["detail"]
    client.post("/api/scan", json={"token": make_token("location", location_id)}, headers=h)
    assert client.post(path, json={}, headers=h).status_code == 200


def test_only_settings_managers_get_the_printable_codes(client, login):
    assert client.get("/api/scan/codes", params={"base": BASE}, headers=login(STEWARD)).status_code == 403
    r = client.get("/api/scan/codes", params={"base": BASE}, headers=login(MGR))
    assert r.status_code == 200
    first = r.json()["points"][0]
    assert first["url"].startswith(f"{BASE}/scan/e") and first["svg"].lstrip().startswith("<?xml")
    assert client.get("/api/scan/codes", params={"base": "javascript:alert(1)"}, headers=login(MGR)).status_code == 422
