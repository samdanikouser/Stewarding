from datetime import date

from sqlalchemy import select

from app.models import Employee, Location, Shift
from app.models.core import CYCLE_EPOCH

MGR = "manager@example.test"
SUP = "sup.mk@example.test"
MONDAY = date(2026, 3, 2)


def week_of(day):
    return ((day - CYCLE_EPOCH).days // 7) % 2


def assign(client, headers, db, location_code, cycle_week, cycle_weeks=2):
    return client.post("/api/roster/assignments", headers=headers, json={
        "employee_id": db.scalar(select(Employee.id).where(Employee.employee_code == "E002")),
        "shift_id": db.scalar(select(Shift.id).where(Shift.name == "Morning")),
        "location_id": db.scalar(select(Location.id).where(Location.code == location_code)),
        "weekdays": [0], "valid_from": "2026-01-05", "cycle_weeks": cycle_weeks, "cycle_week": cycle_week})


def test_alternate_weeks_at_two_locations_do_not_clash(client, login, db):
    m = login(MGR)
    assert assign(client, m, db, "MK", week_of(MONDAY)).status_code == 201
    assert assign(client, m, db, "BQ", 1 - week_of(MONDAY)).status_code == 201


def test_an_overlapping_pattern_is_refused(client, login, db):
    m = login(MGR)
    assert assign(client, m, db, "MK", week_of(MONDAY)).status_code == 201
    assert assign(client, m, db, "MK", 0, cycle_weeks=1).status_code == 409
    assert assign(client, m, db, "MK", week_of(MONDAY)).status_code == 409


def test_the_week_of_the_cycle_must_be_inside_it(client, login, db):
    assert assign(client, login(MGR), db, "MK", 2).status_code == 422


def test_todays_location_follows_the_week(client, login, db, clock):
    m = login(MGR)
    assign(client, m, db, "MK", week_of(MONDAY))
    assign(client, m, db, "BQ", 1 - week_of(MONDAY))
    h = login(SUP)
    here = client.get("/api/attendance/me/status", headers=h).json()["rostered_today"]
    assert [r["location_id"] for r in here] == [db.scalar(select(Location.id).where(Location.code == "MK"))]
    clock.advance(days=7)
    there = client.get("/api/attendance/me/status", headers=h).json()["rostered_today"]
    assert [r["location_id"] for r in there] == [db.scalar(select(Location.id).where(Location.code == "BQ"))]


def test_the_roster_for_a_location_lists_only_the_weeks_that_apply(client, login, db, clock):
    m = login(MGR)
    assign(client, m, db, "MK", 1 - week_of(MONDAY))
    mk = db.scalar(select(Location.id).where(Location.code == "MK"))
    assert "Sam Supervisor" not in [r["name"] for r in client.get(f"/api/roster/today?location_id={mk}", headers=m).json()]
    clock.advance(days=7)
    assert "Sam Supervisor" in [r["name"] for r in client.get(f"/api/roster/today?location_id={mk}", headers=m).json()]
