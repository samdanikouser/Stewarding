from sqlalchemy import select

from app.models import Equipment, EquipmentSchedule, Notification

from .helpers import MGR, STEWARD, SUP, loc_id
from .test_monitoring_general import due_for

FIELDS = [
    {"title": "Product", "value_type": "text", "max_length": 40},
    {"title": "Core temperature", "value_type": "number", "unit": "°C", "min_value": 75, "max_value": 120},
    {"title": "Cooked through", "value_type": "yes_no"},
    {"title": "Method", "value_type": "choice", "options": ["Grill", "Oven", "Fry"], "fail_options": ["Fry"]},
]
DAILY_TWICE = {"mode": "daily", "times": ["12:00:00", "18:00:00"]}


def build(client, h, db, locations=("MK",), fields=None, frequency=None, **over):
    body = {"name": "Cooking log", "kind": "Cooking", "location_ids": [loc_id(db, c) for c in locations],
            "fields": FIELDS if fields is None else fields, "frequency": frequency or DAILY_TWICE, **over}
    return client.post("/api/equipment/forms", json=body, headers=h)


def answers(sched_by_stage, **given):
    spec = {"Product": {"answer": "Chicken thigh"}, "Core temperature": {"value": 82}, "Cooked through": {"value": 1}, "Method": {"answer": "Grill"}}
    spec.update(given)
    return [{"schedule_id": sched_by_stage[title]["id"], **spec[title]} for title in spec]


def test_a_form_becomes_a_point_per_location_with_a_check_per_field_and_time(client, login, db):
    r = build(client, login(MGR), db, locations=("MK", "BQ"))
    assert r.status_code == 201
    points = r.json()["points"]
    assert [p["code"] for p in points] == ["FM-MK-1", "FM-BQ-1"] and {p["name"] for p in points} == {"Cooking log"}
    assert {p["kind"] for p in points} == {"Cooking"}
    assert all(len(p["schedules"]) == 8 for p in points)  # four fields at two times
    first = points[0]["schedules"]
    assert {s["value_type"] for s in first} == {"text", "number", "yes_no", "choice"}
    method = next(s for s in first if s["stage"] == "Method")
    assert method["options"] == ["Grill", "Oven", "Fry"] and method["fail_options"] == ["Fry"]
    assert next(s for s in first if s["stage"] == "Product")["max_length"] == 40
    assert {str(s["time_of_day"])[:5] for s in first} == {"12:00", "18:00"}
    again = build(client, login(MGR), db).json()["points"][0]["code"]
    assert again == "FM-MK-2"


def test_every_field_is_recorded_together_and_judged_by_its_own_rules(client, login, db, clock):
    clock.set(2026, 3, 2, 8, 30)
    point = build(client, login(MGR), db).json()["points"][0]
    steward = login(STEWARD)
    noon = {s["stage"]: s for s in point["schedules"] if str(s["time_of_day"]).startswith("12:00")}
    due = due_for(client, steward, point)
    assert len({d["slot_at"] for d in due}) == 2
    r = client.post("/api/monitoring/readings/batch", json={"equipment_id": point["id"], "readings": answers(noon)}, headers=steward)
    assert r.status_code == 201
    got = {x["stage"]: x for x in r.json()}
    assert got["Product"]["display"] == "Chicken thigh" and got["Product"]["passed"] is True and got["Product"]["value"] is None
    assert got["Core temperature"]["display"] == "82 °C" and got["Method"]["display"] == "Grill" and got["Cooked through"]["display"] == "Yes"
    assert all(x["passed"] for x in got.values())


def test_a_failing_choice_opens_a_corrective_action(client, login, db, clock):
    clock.set(2026, 3, 2, 8, 30)
    point = build(client, login(MGR), db).json()["points"][0]
    steward = login(STEWARD)
    noon = {s["stage"]: s for s in point["schedules"] if str(s["time_of_day"]).startswith("12:00")}
    items = answers(noon, Method={"answer": "Fry", "corrective_action": "Recooked in the oven"})
    r = client.post("/api/monitoring/readings/batch", json={"equipment_id": point["id"], "readings": items}, headers=steward)
    got = {x["stage"]: x for x in r.json()}
    assert got["Method"]["passed"] is False and got["Method"]["corrective_action"]["status"] == "retest_due"
    assert got["Core temperature"]["passed"] is True
    alert = db.scalar(select(Notification).where(Notification.kind == "monitoring_failed"))
    assert "Fry" in alert.title and "Answered Fry" in alert.body


def test_answers_that_break_a_field_s_restrictions_are_refused_and_nothing_is_saved(client, login, db, clock):
    clock.set(2026, 3, 2, 8, 30)
    point = build(client, login(MGR), db).json()["points"][0]
    steward = login(STEWARD)
    noon = {s["stage"]: s for s in point["schedules"] if str(s["time_of_day"]).startswith("12:00")}
    from app.models import TemperatureReading

    def attempt(**given):
        return client.post("/api/monitoring/readings/batch", json={"equipment_id": point["id"], "readings": answers(noon, **given)}, headers=steward)

    assert attempt(Product={"answer": "x" * 41}).status_code == 400            # longer than the field allows
    assert attempt(Product={"answer": "   "}).status_code == 400               # blank
    assert attempt(Method={"answer": "Boil"}).status_code == 400               # not one of the choices
    assert attempt(**{"Core temperature": {}}).status_code == 400              # a number is needed
    assert attempt(**{"Cooked through": {"value": 2}}).status_code == 400
    assert db.query(TemperatureReading).count() == 0
    assert attempt(**{"Core temperature": {"value": 60}}).status_code == 201   # out of range is accepted and flagged, not refused


def test_the_form_definition_is_validated(client, login, db):
    m = login(MGR)

    def bad(**over):
        r = build(client, m, db, **over)
        assert r.status_code in (400, 404, 422), (over, r.status_code)
        assert db.query(Equipment).filter(Equipment.code.like("FM-%")).count() == 0

    bad(fields=[{"title": "A field", "value_type": "number"}])                                   # a number needs a limit
    bad(fields=[{"title": "Method", "value_type": "choice", "options": ["Only one"]}])
    bad(fields=[{"title": "Method", "value_type": "choice", "options": ["A", "B"], "fail_options": ["C"]}])
    bad(fields=[{"title": "Same", "value_type": "text"}, {"title": " same ", "value_type": "yes_no"}])
    bad(fields=[{"title": "Odd", "value_type": "photo"}])
    bad(fields=[])
    bad(name=" ")
    bad(location_ids=[9999])
    bad(location_ids=[])
    bad(frequency={"mode": "weekly", "times": ["08:00:00"]})
    bad(frequency={"mode": "monthly", "times": ["08:00:00"]})
    bad(frequency={"mode": "daily", "times": []})
    bad(frequency={"mode": "daily", "times": ["08:00:00", "08:00:00"]})
    bad(frequency={"mode": "interval", "interval_minutes": 60})
    bad(frequency={"mode": "interval", "interval_minutes": 1, "start": "06:00:00"})
    bad(frequency={"mode": "weekly", "weekdays": [8], "times": ["08:00:00"]})


def test_each_frequency_becomes_the_matching_schedule(client, login, db):
    m = login(MGR)
    weekly = build(client, m, db, fields=[FIELDS[2]], frequency={"mode": "weekly", "weekdays": [4, 1], "times": ["09:00:00"]}).json()["points"][0]["schedules"][0]
    assert weekly["weekdays"] == [1, 4] and weekly["timing"] == "checkpoint"
    monthly = build(client, m, db, fields=[FIELDS[2]], frequency={"mode": "monthly", "day_of_month": 3, "times": ["09:00:00"]}).json()["points"][0]["schedules"][0]
    assert monthly["day_of_month"] == 3
    hourly = build(client, m, db, fields=[FIELDS[2]], frequency={"mode": "interval", "interval_minutes": 120, "start": "06:00:00"}).json()["points"][0]["schedules"][0]
    assert hourly["timing"] == "interval" and hourly["interval_minutes"] == 120 and str(hourly["time_of_day"]).startswith("06:00")


def test_only_a_manager_creates_forms_and_the_audit_is_kept(client, login, db):
    for who in (SUP, STEWARD):
        assert build(client, login(who), db).status_code == 403
    assert client.post("/api/equipment/forms", json={}).status_code == 401
    build(client, login(MGR), db)
    assert db.scalar(select(EquipmentSchedule.id).where(EquipmentSchedule.stage == "Method"))


def test_the_record_shows_written_answers(client, login, db, clock):
    clock.set(2026, 3, 2, 8, 30)
    point = build(client, login(MGR), db).json()["points"][0]
    steward = login(STEWARD)
    noon = {s["stage"]: s for s in point["schedules"] if str(s["time_of_day"]).startswith("12:00")}
    client.post("/api/monitoring/readings/batch", json={"equipment_id": point["id"], "readings": answers(noon)}, headers=steward)
    doc = client.get("/api/reports/records/monitoring?date_from=2026-03-02&date_to=2026-03-02", headers=login(MGR)).json()
    rows = {r["check"]: r for g in doc["groups"] for r in g["rows"]}
    assert rows["Product"]["value"] == "Chicken thigh" and rows["Method"]["value"] == "Grill" and rows["Core temperature"]["value"] == "82 °C"
