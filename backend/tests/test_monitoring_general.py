from sqlalchemy import select

from app.models import Notification

from .helpers import MGR, STEWARD, SUP, loc_id, make_lot


def point(client, h, db, kind="Sanitising", code="SN-T-1", loc="MK"):
    body = {"code": code, "name": "Test point", "kind": kind, "location_id": loc_id(db, loc)}
    return client.post("/api/equipment", json=body, headers=h).json()


def check(client, h, eq, **over):
    body = {"stage": "Strength", "parameter": "Concentration", "unit": "ppm", "value_type": "number", "timing": "checkpoint",
            "time_of_day": "07:00:00", "min_value": 200, "max_value": 400, **over}
    return client.post(f"/api/equipment/{eq['id']}/schedules", json=body, headers=h)


def record(client, h, eq, sched, value, **extra):
    return client.post("/api/monitoring/readings", headers=h,
                       json={"equipment_id": eq["id"], "schedule_id": sched["id"], "value": value, **extra})


def due_for(client, h, eq):
    return [d for d in client.get("/api/monitoring/due", headers=h).json() if d["equipment_id"] == eq["id"]]


def test_a_ppm_check_passes_and_fails_against_its_own_limits(client, login, db, clock):
    clock.set(2026, 3, 2, 4, 0)
    m = login(MGR)
    eq = point(client, m, db)
    sched = check(client, m, eq).json()
    low = record(client, login(STEWARD), eq, sched, 150).json()
    assert low["passed"] is False and low["display"] == "150 ppm" and low["unit"] == "ppm"
    clock.advance(days=1)
    ok = record(client, login(STEWARD), eq, sched, 300).json()
    assert ok["passed"] is True and ok["parameter"] == "Concentration"
    alert = db.scalar(select(Notification).where(Notification.kind == "monitoring_failed"))
    assert "150 ppm" in alert.title and "Limits 200" in alert.body


def test_yes_no_checks_need_no_limits_and_only_yes_passes(client, login, db, clock):
    clock.set(2026, 3, 2, 4, 0)
    m = login(MGR)
    eq = point(client, m, db, kind="Defrosting", code="DF-T-1")
    sched = check(client, m, eq, stage="Defrosted", parameter="Check", unit=None, value_type="yes_no",
                  min_value=None, max_value=None).json()
    assert sched["min_value"] is None and sched["unit"] is None
    assert record(client, m, eq, sched, 2).status_code == 400
    no = record(client, m, eq, sched, 0).json()
    assert no["passed"] is False and no["display"] == "No"
    clock.advance(days=1)
    assert record(client, m, eq, sched, 1).json()["display"] == "Yes"


def test_a_check_can_demand_a_batch_reference(client, login, db, clock):
    clock.set(2026, 3, 2, 4, 0)
    m = login(MGR)
    eq = point(client, m, db, kind="Cooking", code="CK-T-1")
    sched = check(client, m, eq, stage="Core", parameter="Temperature", unit="°C", min_value=75, max_value=120,
                  require_reference=True).json()
    missing = record(client, m, eq, sched, 80)
    assert missing.status_code == 400 and "reference" in missing.json()["detail"]
    saved = record(client, m, eq, sched, 80, reference="  Chicken batch 12 ").json()
    assert saved["reference"] == "Chicken batch 12" and saved["passed"] is True


def test_weekly_and_monthly_checks_are_due_only_on_their_days(client, login, db, clock):
    m = login(MGR)
    eq = point(client, m, db, kind="Calibration", code="PC-T-1")
    tuesday = check(client, m, eq, stage="Weekly", weekdays=[1]).json()
    third = check(client, m, eq, stage="Monthly", day_of_month=3).json()
    second = check(client, m, eq, stage="Monthly 2nd", day_of_month=2).json()
    assert tuesday["weekdays"] == [1]
    today = {d["schedule_id"] for d in due_for(client, m, eq)}  # Monday the 2nd
    assert today == {second["id"]}
    clock.set(2026, 3, 3, 2, 5)
    assert {d["schedule_id"] for d in due_for(client, m, eq)} == {tuesday["id"], third["id"]}


def test_check_configuration_is_validated(client, login, db):
    m = login(MGR)
    eq = point(client, m, db)
    assert check(client, m, eq, min_value=None, max_value=None).status_code == 422  # a number needs a limit
    assert check(client, m, eq, weekdays=[9]).status_code == 422
    assert check(client, m, eq, day_of_month=32).status_code == 422
    assert check(client, m, eq, value_type="photo").status_code == 422


def test_templates_create_ready_made_monitoring_points(client, login, db):
    m = login(MGR)
    assert client.get("/api/equipment/templates", headers=login(SUP)).status_code == 403
    keys = {t["key"] for t in client.get("/api/equipment/templates", headers=m).json()}
    assert {"chiller", "freezer", "defrosting", "cooking", "reheating", "cooling", "goods_receiving"} <= keys
    first = client.post("/api/equipment/from-template", json={"template": "chiller", "location_id": loc_id(db, "MK")}, headers=m)
    assert first.status_code == 201
    body = first.json()
    assert body["code"] == "CH-MK-1" and body["kind"] == "Cold storage" and len(body["schedules"]) == 2
    assert body["schedules"][0]["max_value"] == "5.00" or float(body["schedules"][0]["max_value"]) == 5
    second = client.post("/api/equipment/from-template", json={"template": "chiller", "location_id": loc_id(db, "MK"),
                                                               "name": "Bar fridge"}, headers=m).json()
    assert second["code"] == "CH-MK-2" and second["name"] == "Bar fridge"
    assert client.post("/api/equipment/from-template", json={"template": "nope", "location_id": loc_id(db, "MK")}, headers=m).status_code == 400
    assert client.post("/api/equipment/from-template", json={"template": "chiller", "location_id": loc_id(db, "MK")},
                       headers=login(SUP)).status_code == 403


def test_every_template_check_can_be_recorded(client, login, db, clock):
    clock.set(2026, 3, 2, 18, 30)
    m = login(MGR)
    templates = client.get("/api/equipment/templates", headers=m).json()
    for t in templates:
        made = client.post("/api/equipment/from-template", json={"template": t["key"], "location_id": loc_id(db, "RB")}, headers=m).json()
        started = None
        for sched in sorted(made["schedules"], key=lambda c: c["phase"] == "finish"):
            value = 1 if sched["value_type"] == "yes_no" else (float(sched["min_value"] or 0) + float(sched["max_value"] or 0)) / 2
            extra = {"reference": "Batch 1"} if sched["require_reference"] else {}
            if sched["trace_lots"] and sched["phase"] != "finish":
                extra["lot_ids"] = [make_lot(made["location_id"])]
            if sched["phase"] == "finish":
                extra["start_reading_id"] = started
            r = record(client, m, made, sched, value, **extra)
            assert r.status_code == 201 and r.json()["passed"] is True, (t["key"], sched["stage"], r.text)
            if sched["phase"] == "start":
                started = r.json()["id"]
