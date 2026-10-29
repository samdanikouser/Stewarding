from sqlalchemy import select

from app.models import Notification, ShiftAssignment

from .helpers import MGR, SUP, loc_id
from .test_absences import day_row, emp_id, record


def weekoff_shift(client, h):
    body = {"kind": "weekoff", "name": "Rest Day", "start_time": "09:00", "end_time": "17:00", "grace_minutes": 30}
    return client.post("/api/roster/shifts", json=body, headers=h)


def assign(client, h, db, shift, code="E004", loc="MK", weekdays=(0,), valid_from="2026-03-01", valid_to=None):
    return client.post("/api/roster/assignments", headers=h, json={
        "employee_id": emp_id(client, h, code), "shift_id": shift, "location_id": loc_id(db, loc),
        "weekdays": list(weekdays), "valid_from": valid_from, "valid_to": valid_to})


def test_week_off_shift_has_no_hours_and_is_listed_first(client, login):
    h = login(MGR)
    made = weekoff_shift(client, h).json()
    assert made["kind"] == "weekoff" and made["start_time"] == "00:00:00" and made["grace_minutes"] == 0
    assert client.get("/api/roster/shifts", headers=h).json()[0]["kind"] == "weekoff"


def clear_days(client, h, code="E004", weekdays=(0,)):
    for a in client.get(f"/api/roster/assignments?employee_id={emp_id(client, h, code)}", headers=h).json():
        if a["weekday"] in weekdays:
            client.delete(f"/api/roster/assignments/{a['id']}", headers=h)


def test_week_off_conflicts_with_a_working_shift_on_the_same_weekday(client, login, db, clock):
    h = login(MGR)
    off = weekoff_shift(client, h).json()["id"]
    assert assign(client, h, db, off, weekdays=(0,)).status_code == 409  # Sid already works Mondays
    clear_days(client, h, weekdays=(5,))
    assert assign(client, h, db, off, weekdays=(5,), valid_from="2026-03-09").status_code == 201


def test_a_shift_cannot_change_kind_once_assigned(client, login, db):
    h = login(MGR)
    shifts = client.get("/api/roster/shifts", headers=h).json()
    work = next(s for s in shifts if s["kind"] == "work")
    body = {**work, "kind": "weekoff"}
    assert client.put(f"/api/roster/shifts/{work['id']}", json=body, headers=h).status_code == 409


def test_week_off_day_is_flagged_not_scheduled_and_not_chased(client, login, db, clock):
    h = login(MGR)
    off = weekoff_shift(client, h).json()["id"]
    clear_days(client, h)
    assert assign(client, h, db, off, weekdays=(0,), valid_from="2026-03-09").status_code == 201
    clock.set(2026, 3, 9, 2, 5)  # the following Monday, after the working Monday ended
    assert day_row(client, h, db)["day_type"] == "week_off"
    k = client.get("/api/dashboard", headers=h).json()
    assert k["kpis"]["off_today"] >= 1 and k["kpis"]["scheduled_today"] == 2
    from app.services import alerts
    from app.db import SessionLocal
    clock.set(2026, 3, 9, 4, 0)
    with SessionLocal() as s:
        alerts.run_alerts(s, clock.now)
        assert not [n for n in s.scalars(select(Notification)) if "Sid Steward" in (n.body or "")]


def test_an_assignment_can_end_on_a_date_that_is_checked_listed_and_used_for_clashes(client, login, db, clock):
    h = login(MGR)
    off = weekoff_shift(client, h).json()["id"]
    work = next(s["id"] for s in client.get("/api/roster/shifts", headers=h).json() if s["kind"] == "work")
    clear_days(client, h, weekdays=(5,))
    assert assign(client, h, db, off, weekdays=(5,), valid_from="2026-03-09", valid_to="2026-03-01").status_code == 422
    assert assign(client, h, db, off, weekdays=(5,), valid_from="2026-03-09", valid_to="2026-03-31").status_code == 201
    saturday = [a for a in client.get(f"/api/roster/assignments?employee_id={emp_id(client, h)}", headers=h).json() if a["weekday"] == 5 and a["valid_from"] == "2026-03-09"]
    assert [a["valid_to"] for a in saturday] == ["2026-03-31"]
    assert assign(client, h, db, work, weekdays=(5,), valid_from="2026-03-20", valid_to="2026-04-10").status_code == 409
    assert assign(client, h, db, work, weekdays=(5,), valid_from="2026-04-01").status_code == 201
    assert assign(client, h, db, work, weekdays=(5,), valid_from="2026-03-03", valid_to="2026-03-08").status_code == 201


def test_the_same_shift_cannot_be_assigned_over_days_it_is_still_active_and_today_lists_each_person_once(client, login, db, clock):
    h = login(MGR)
    sid = emp_id(client, h, "E004")
    monday = next(a for a in client.get(f"/api/roster/assignments?employee_id={sid}", headers=h).json() if a["weekday"] == 0)
    again = assign(client, h, db, monday["shift_id"], weekdays=(0,), valid_from="2026-03-02")
    assert again.status_code == 409 and "already has" in again.json()["detail"]
    assert assign(client, h, db, monday["shift_id"], weekdays=(0,), valid_from="2024-01-01", valid_to="2024-12-31").status_code == 201
    db.add(ShiftAssignment(employee_id=sid, shift_id=monday["shift_id"], location_id=loc_id(db, "MK"), weekday=0, valid_from=clock.now.date()))
    db.commit()
    today = client.get(f"/api/roster/today?location_id={loc_id(db, 'MK')}", headers=h).json()
    assert [p["employee_id"] for p in today].count(sid) == 1


def test_a_whole_week_of_one_shift_is_ended_in_one_call(client, login, db, clock):
    h = login(MGR)
    morning = next(s["id"] for s in client.get("/api/roster/shifts", headers=h).json() if s["name"] == "Morning")
    clear_days(client, h, weekdays=range(7))
    ids = assign(client, h, db, morning, weekdays=range(7), valid_from="2026-03-03").json()["ids"]
    assert len(ids) == 7
    assert client.post("/api/roster/assignments/end", json={"ids": ids}, headers=login("steward.mk@example.test")).status_code == 403
    assert client.post("/api/roster/assignments/end", json={"ids": [ids[0], 999999]}, headers=h).status_code == 404
    assert client.post("/api/roster/assignments/end", json={"ids": ids}, headers=h).json() == {"ended": 7}
    mine = [a for a in client.get(f"/api/roster/assignments?employee_id={emp_id(client, h, 'E004')}", headers=h).json() if a["id"] in ids]
    assert len(mine) == 7 and {a["valid_to"] for a in mine} == {"2026-03-03"}


def test_a_group_of_assignments_is_edited_in_one_call_and_checked_like_a_new_one(client, login, db, clock):
    h = login(MGR)
    shifts = {s["name"]: s["id"] for s in client.get("/api/roster/shifts", headers=h).json()}
    clear_days(client, h, weekdays=range(7))
    ids = assign(client, h, db, shifts["Morning"], weekdays=(0, 1, 2), valid_from="2026-03-03").json()["ids"]
    mine = emp_id(client, h, "E004")
    changed = client.put("/api/roster/assignments", headers=h, json={
        "ids": ids, "shift_id": shifts["Evening"], "weekdays": [0, 4], "valid_from": "2026-03-03"})
    assert changed.status_code == 200 and len(changed.json()["ids"]) == 2
    rows = [a for a in client.get(f"/api/roster/assignments?employee_id={mine}", headers=h).json() if a["id"] in changed.json()["ids"]]
    assert sorted(a["weekday"] for a in rows) == [0, 4] and {a["shift_id"] for a in rows} == {shifts["Evening"]}
    started = [a for a in client.get(f"/api/roster/assignments?employee_id={mine}", headers=h).json() if a["valid_from"] == "2026-03-03"]
    assert sorted(a["weekday"] for a in started) == [0, 4]
    off = weekoff_shift(client, h).json()["id"]
    assert assign(client, h, db, off, weekdays=(4,), valid_from="2026-03-03").status_code == 409
    again = client.put("/api/roster/assignments", headers=h, json={"ids": changed.json()["ids"], "shift_id": shifts["Evening"], "weekdays": [4], "valid_from": "2026-03-03"})
    assert again.status_code == 200
    assert client.put("/api/roster/assignments", headers=login("steward.mk@example.test"), json={"ids": again.json()["ids"], "shift_id": shifts["Evening"], "weekdays": [4], "valid_from": "2026-03-03"}).status_code == 403
    assert client.put("/api/roster/assignments", headers=h, json={"ids": [999999], "shift_id": shifts["Evening"], "weekdays": [4], "valid_from": "2026-03-03"}).status_code == 404


def test_a_group_of_assignments_can_be_removed_entirely(client, login, db, clock):
    h = login(MGR)
    morning = next(s["id"] for s in client.get("/api/roster/shifts", headers=h).json() if s["name"] == "Morning")
    clear_days(client, h, weekdays=range(7))
    ids = assign(client, h, db, morning, weekdays=(1, 2), valid_from="2026-03-03").json()["ids"]
    assert client.post("/api/roster/assignments/remove", json={"ids": ids}, headers=login("steward.mk@example.test")).status_code == 403
    assert client.post("/api/roster/assignments/remove", json={"ids": ids}, headers=h).json() == {"removed": 2}
    assert not [a for a in client.get(f"/api/roster/assignments?employee_id={emp_id(client, h, 'E004')}", headers=h).json() if a["valid_from"] == "2026-03-03"]
    assert client.post("/api/roster/assignments/remove", json={"ids": ids}, headers=h).status_code == 404
