from datetime import date, datetime, time

from sqlalchemy import select

from app import timeutil
from app.models import AttendanceCorrection, AttendanceRecord, AuditLog, Location

MGR = "manager@example.test"
STEWARD = "steward.mk@example.test"


def loc_id(db, code):
    return db.scalar(select(Location.id).where(Location.code == code))


def check_in(client, h, db, code="MK", **extra):
    return client.post("/api/attendance/check-in", json={"location_id": loc_id(db, code), **extra}, headers=h)


def test_check_in_on_time_records_server_time_and_shift(client, login, db, clock):
    r = check_in(client, login(STEWARD), db)
    assert r.status_code == 201
    body = r.json()
    assert body["late_minutes"] == 0 and body["shift_id"] and body["check_in_at"] == "2026-03-02T02:05:00Z"


def test_late_check_in_is_flagged_against_shift_grace(client, login, db, clock):
    clock.set(2026, 3, 2, 2, 30)
    assert check_in(client, login(STEWARD), db).json()["late_minutes"] == 30
    clock.set(2026, 3, 2, 2, 9)
    # a different employee inside the 10 minute grace window is not late
    assert check_in(client, login("steward.bq@example.test"), db, "BQ").json()["late_minutes"] == 0


def test_duplicate_active_check_in_is_rejected(client, login, db, clock):
    h = login(STEWARD)
    assert check_in(client, h, db).status_code == 201
    assert check_in(client, h, db).status_code == 409


def test_check_out_needs_active_check_in(client, login, clock):
    assert client.post("/api/attendance/check-out", json={}, headers=login(STEWARD)).status_code == 409


def test_cannot_check_in_at_unassigned_location(client, login, db, clock):
    assert check_in(client, login(STEWARD), db, "RB").status_code == 403


def test_check_in_uses_location_local_date_across_midnight(client, login, db, clock):
    clock.set(2026, 3, 1, 21, 30)  # Sunday 21:30 UTC is Monday 01:30 in Dubai
    body = check_in(client, login(STEWARD), db).json()
    assert body["local_date"] == "2026-03-02"


def test_dst_shift_start_uses_local_offset(client, login, db, clock):
    # London switches to BST on 2026-03-29; 06:05 local is 05:05 UTC and is on time, not an hour late
    clock.set(2026, 3, 29, 5, 5)
    body = check_in(client, login("steward.rb@example.test"), db, "RB").json()
    assert body["late_minutes"] == 0


def fence(db, lat=29.3759, lon=47.9774, radius=100, code="MK"):
    loc = db.get(Location, loc_id(db, code))
    loc.latitude, loc.longitude, loc.geofence_radius_m = lat, lon, radius
    db.commit()


def test_check_in_and_out_are_limited_to_the_geofence(client, login, db, clock):
    fence(db)
    h = login(STEWARD)
    assert check_in(client, h, db).status_code == 400                                      # no position sent
    far = check_in(client, h, db, latitude=29.3859, longitude=47.9774)                     # about 1.1 km north
    assert far.status_code == 403 and "within 100 m" in far.json()["detail"]
    assert check_in(client, h, db, latitude=29.3760, longitude=47.9775).status_code == 201  # about 15 m away
    out = "/api/attendance/check-out"
    assert client.post(out, json={}, headers=h).status_code == 400
    assert client.post(out, json={"latitude": 29.3859, "longitude": 47.9774, "exception_reason": "Left early, covered"}, headers=h).status_code == 403
    assert client.post(out, json={"latitude": 29.3760, "longitude": 47.9775, "exception_reason": "Tasks done elsewhere"}, headers=h).status_code == 200


def test_without_attendance_by_location_the_position_picks_the_place(client, login, db, clock):
    fence(db)
    assert client.put("/api/settings", json={"values": {"attendance.by_location": 0}}, headers=login(MGR)).status_code == 200
    h = login(STEWARD)
    assert client.get("/api/auth/me", headers=h).json()["by_location"] is False
    url = "/api/attendance/check-in"
    assert client.post(url, json={}, headers=h).status_code == 400                                    # position still needed
    assert client.post(url, json={"latitude": 29.3859, "longitude": 47.9774}, headers=h).status_code == 403   # 1.1 km away
    ok = client.post(url, json={"latitude": 29.3760, "longitude": 47.9775}, headers=h)
    assert ok.status_code == 201 and ok.json()["location_id"] == loc_id(db, "MK")


def test_choosing_a_location_is_still_required_when_attendance_is_by_location(client, login, db, clock):
    assert client.post("/api/attendance/check-in", json={}, headers=login(STEWARD)).status_code == 422


def test_a_location_without_a_geofence_needs_no_position(client, login, db, clock):
    assert check_in(client, login(STEWARD), db).status_code == 201


def generate_tasks(client, login, db):
    return client.post("/api/checklists/generate", json={"location_id": loc_id(db, "MK")}, headers=login(MGR))


def test_checkout_blocked_by_mandatory_tasks_unless_exception_given(client, login, db, clock):
    assert generate_tasks(client, login, db).json()["created"] > 0
    h = login(STEWARD)
    check_in(client, h, db)
    blocked = client.post("/api/attendance/check-out", json={}, headers=h)
    assert blocked.status_code == 409 and blocked.json()["detail"]["tasks"]
    assert client.post("/api/attendance/check-out", json={"exception_reason": "no"}, headers=h).status_code == 409
    clock.advance(hours=8)
    ok = client.post("/api/attendance/check-out", json={"exception_reason": "Equipment was down all shift"}, headers=h)
    assert ok.status_code == 200 and ok.json()["exception_reason"]
    assert db.scalar(select(AuditLog.id).where(AuditLog.action == "attendance.checkout_exception"))


def test_payable_and_overtime_minutes(client, login, db, clock):
    h = login(STEWARD)
    check_in(client, h, db)
    clock.advance(hours=9)
    done = client.post("/api/attendance/check-out", json={}, headers=h).json()
    assert done["payable_minutes"] == 540 and done["overtime_minutes"] == 60 and not done["open"]


def test_my_status_reflects_open_shift(client, login, db, clock):
    h = login(STEWARD)
    assert client.get("/api/attendance/me/status", headers=h).json()["checked_in"] is False
    check_in(client, h, db)
    status = client.get("/api/attendance/me/status", headers=h).json()
    assert status["checked_in"] and status["location"]["name"] == "Main Kitchen" and status["shift"] == "Morning"


def test_missed_checkout_is_flagged(client, login, db, clock):
    h = login(STEWARD)
    check_in(client, h, db)
    clock.advance(hours=20)
    items = client.get("/api/attendance", headers=login(MGR)).json()["items"]
    assert items[0]["open"] and items[0]["missed_checkout"]


def test_steward_history_is_private_to_self(client, login, db, clock):
    check_in(client, login(STEWARD), db)
    mine = client.get("/api/attendance/mine", headers=login(STEWARD)).json()
    assert mine["total"] == 1
    assert client.get("/api/attendance", headers=login(STEWARD)).status_code == 403


def test_supervisor_attendance_list_is_location_scoped(client, login, db, clock):
    check_in(client, login("steward.rb@example.test"), db, "RB")
    assert client.get("/api/attendance", headers=login("sup.mk@example.test")).json()["total"] == 0
    assert client.get("/api/attendance", headers=login("sup.rb@example.test")).json()["total"] == 1
    other = client.get(f"/api/attendance?location_id={loc_id(db, 'RB')}", headers=login("sup.mk@example.test"))
    assert other.status_code == 403


def test_correction_needs_permission_keeps_history_and_audits(client, login, db, clock):
    h = login(STEWARD)
    rec = check_in(client, h, db).json()
    clock.advance(hours=8)
    client.post("/api/attendance/check-out", json={}, headers=h)
    new = "2026-03-02T10:30:00+04:00"
    body = {"field": "check_out_at", "new_value": new, "reason": "Forgot to check out on time"}
    assert client.post(f"/api/attendance/{rec['id']}/correct", json=body, headers=h).status_code == 403
    assert client.post(f"/api/attendance/{rec['id']}/correct", json=body, headers=login("sup.mk@example.test")).status_code == 403
    ok = client.post(f"/api/attendance/{rec['id']}/correct", json=body, headers=login(MGR))
    assert ok.status_code == 200 and ok.json()["check_out_at"] == "2026-03-02T06:30:00Z"
    correction = db.scalar(select(AttendanceCorrection))
    assert correction.old_value == "2026-03-02T10:05:00Z" and correction.new_value == "2026-03-02T06:30:00Z"
    assert db.scalar(select(AuditLog.id).where(AuditLog.action == "attendance.correct"))


def test_correction_validation(client, login, db, clock):
    h = login(STEWARD)
    rec = check_in(client, h, db).json()
    m = login(MGR)
    early = {"field": "check_out_at", "new_value": "2026-03-02T01:00:00Z", "reason": "bad time entered"}
    assert client.post(f"/api/attendance/{rec['id']}/correct", json=early, headers=m).status_code == 400
    naive = {"field": "check_in_at", "new_value": "2026-03-02T05:00:00", "reason": "no offset given"}
    assert client.post(f"/api/attendance/{rec['id']}/correct", json=naive, headers=m).status_code == 422
    short = {"field": "check_in_at", "new_value": "2026-03-02T05:00:00Z", "reason": "no"}
    assert client.post(f"/api/attendance/{rec['id']}/correct", json=short, headers=m).status_code == 422


def test_roster_today_shows_who_checked_in(client, login, db, clock):
    mk = loc_id(db, "MK")
    before = client.get(f"/api/roster/today?location_id={mk}", headers=login("sup.mk@example.test")).json()
    assert [(r["name"], r["checked_in"]) for r in before] == [("Sid Steward", False)]
    check_in(client, login(STEWARD), db)
    after = client.get(f"/api/roster/today?location_id={mk}", headers=login("sup.mk@example.test")).json()
    assert after[0]["checked_in"] and after[0]["on_duty"]
    assert client.get(f"/api/roster/today?location_id={loc_id(db, 'RB')}", headers=login("sup.mk@example.test")).status_code == 403


def test_roster_assignment_rules(client, login, db, clock):
    m = login(MGR)
    emps = {e["employee_code"]: e["id"] for e in client.get("/api/employees?size=50", headers=m).json()["items"]}
    shifts = client.get("/api/roster/shifts", headers=m).json()
    evening = next(s["id"] for s in shifts if s["name"] == "Evening")
    body = {"employee_id": emps["E004"], "shift_id": evening, "location_id": loc_id(db, "MK"),
            "weekdays": [0, 1], "valid_from": "2026-03-01"}
    assert client.post("/api/roster/assignments", json=body, headers=login(STEWARD)).status_code == 403
    assert client.post("/api/roster/assignments", json=body, headers=m).status_code == 201
    assert client.post("/api/roster/assignments", json=body, headers=m).status_code == 409
    wrong = {**body, "location_id": loc_id(db, "RB")}
    assert client.post("/api/roster/assignments", json=wrong, headers=m).status_code == 400


def test_dst_conversion_helpers():
    assert timeutil.local_to_utc(date(2026, 3, 28), time(12, 0), "Europe/London") == datetime(2026, 3, 28, 12, 0)
    assert timeutil.local_to_utc(date(2026, 3, 29), time(12, 0), "Europe/London") == datetime(2026, 3, 29, 11, 0)
    assert timeutil.shift_minutes(time(22, 0), time(6, 0)) == 480


def test_the_position_is_kept_and_suspicious_punches_are_flagged(client, login, db, clock):
    fence(db)
    h = login(STEWARD)
    first = check_in(client, h, db, latitude=29.37601, longitude=47.97751, accuracy=12)
    assert first.status_code == 201 and first.json()["geo_flags"] == []
    out = client.post("/api/attendance/check-out", json={"latitude": 29.37601, "longitude": 47.97751, "accuracy": 12, "exception_reason": "Tasks done elsewhere"}, headers=h)
    assert out.json()["geo_flags"] == ["Same position as the last punch"]
    clock.advance(minutes=30)
    jump = check_in(client, h, db, latitude=29.37602, longitude=47.97752)
    assert jump.json()["geo_flags"] == ["No accuracy reported"]
    saved = db.scalar(select(AttendanceRecord).where(AttendanceRecord.id == first.json()["id"]))
    assert saved.check_in_geo["accuracy"] == 12 and saved.check_in_geo["distance"] < 30


def test_a_vague_position_is_refused_and_the_limit_is_a_setting(client, login, db, clock):
    fence(db)
    h = login(STEWARD)
    vague = check_in(client, h, db, latitude=29.3760, longitude=47.9775, accuracy=400)
    assert vague.status_code == 400 and "too imprecise" in vague.json()["detail"]
    assert client.put("/api/settings", json={"values": {"attendance.max_accuracy_m": 0}}, headers=login(MGR)).status_code == 200
    assert check_in(client, h, db, latitude=29.3760, longitude=47.9775, accuracy=400).status_code == 201


def test_flags_show_in_the_attendance_listing_and_record(client, login, db, clock):
    fence(db)
    check_in(client, login(STEWARD), db, latitude=29.3760, longitude=47.9775)
    m = login(MGR)
    listing = client.get("/api/attendance", headers=m).json()["items"]
    assert listing[0]["geo_flags"] == ["No accuracy reported"]
    doc = client.get("/api/reports/records/attendance?date_from=2026-03-02&date_to=2026-03-02", headers=m).json()
    sid = next(r for g in doc["groups"] for r in g["rows"] if r["employee"] == "Sid Steward")
    assert sid["location_check"] == "No accuracy reported"


def test_my_schedule_lists_each_day_of_the_month_with_shifts_week_offs_and_leave(client, login, db, clock):
    h = login(STEWARD)
    month = client.get("/api/attendance/me/schedule?month=2026-03", headers=h).json()
    assert month["month"] == "2026-03" and len(month["days"]) == 31
    monday = next(d for d in month["days"] if d["date"] == "2026-03-02")
    assert [s["name"] for s in monday["shifts"]] and monday["shifts"][0]["location"] and not monday["shifts"][0]["week_off"]
    assert client.get("/api/attendance/me/schedule?month=nonsense", headers=h).status_code == 422
    assert len(client.get("/api/attendance/me/schedule", headers=h).json()["days"]) >= 28        # this month by default


def test_my_schedule_marks_what_happened_on_past_days(client, login, db, clock):
    h = login(STEWARD)
    assert check_in(client, h, db).status_code == 201                                  # Monday 2 March, on time
    clock.set(2026, 3, 9, 7, 0)                                                         # a week later
    month = {d["date"]: d for d in client.get("/api/attendance/me/schedule?month=2026-03", headers=h).json()["days"]}
    assert month["2026-03-02"]["outcome"] == "on_duty" and month["2026-03-02"]["worked"][0]["check_in_at"]
    assert month["2026-03-09"]["outcome"] is None                                       # today, nothing punched yet
    unpunched = [d for d in month.values() if d["date"] < "2026-03-09" and not d["worked"] and any(not s["week_off"] for s in d["shifts"])]
    assert unpunched and all(d["outcome"] == "missed" for d in unpunched)                # rostered, no punch, no leave


def test_leave_and_missed_attendance_can_be_recorded_without_choosing_a_location(client, login, db, clock):
    m = login(MGR)
    emp = next(e for e in client.get("/api/employees?size=100", headers=m).json()["items"] if e["email"] == "steward.mk@example.test")
    off = client.post("/api/absences", json={"employee_id": emp["id"], "day": "2026-03-04", "absence_type": "day_off"}, headers=m)
    assert off.status_code == 201, off.text
    assert off.json()["location_id"] == emp["location_ids"][0]                                  # the place they work at
    manual = client.post("/api/attendance/manual", json={"employee_id": emp["id"], "day": "2026-03-01", "check_in_time": "06:00:00",
                                                         "check_out_time": "14:00:00", "reason": "Forgot to check in"}, headers=m)
    assert manual.status_code == 201, manual.text
    assert manual.json()["location_id"] == emp["location_ids"][0]
    # an employee tied to no location works anywhere, so leave can be marked for them too
    free = client.post("/api/employees", json={"full_name": "Free Roamer", "job_title": "Cook", "email": "free@example.com", "password": "a-long-test-password",
                                               "role": "steward", "location_ids": []}, headers=m).json()
    assert client.post("/api/absences", json={"employee_id": free["id"], "day": "2026-03-04", "absence_type": "sick_leave"}, headers=m).status_code == 201
    # naming a location the employee does not work at is still refused
    other = next(i for i in range(1, 10) if i not in emp["location_ids"])
    assert client.post("/api/absences", json={"employee_id": emp["id"], "location_id": other, "day": "2026-03-05", "absence_type": "day_off"}, headers=m).status_code == 400


def night_roster(db, code="MK"):
    from datetime import date, time
    from app.models import Employee, Shift, ShiftAssignment
    emp = db.scalar(select(Employee).where(Employee.email == "steward.mk@example.test"))
    for a in db.scalars(select(ShiftAssignment).where(ShiftAssignment.employee_id == emp.id)):
        db.delete(a)
    night = Shift(name="Night", start_time=time(17, 0), end_time=time(5, 0), kind="work", grace_minutes=10)
    db.add(night)
    db.flush()
    for weekday in range(7):
        db.add(ShiftAssignment(employee_id=emp.id, shift_id=night.id, location_id=loc_id(db, code), weekday=weekday, valid_from=date(2026, 1, 1)))
    db.commit()
    return emp, night


def test_a_night_shift_worker_arriving_after_midnight_is_late_for_last_nights_shift_not_early_for_tonights(client, login, db, clock):
    from app.services import metrics
    emp, night = night_roster(db)
    clock.set(2026, 3, 2, 20, 30)                                         # 00:30 on Tuesday 3 March in Dubai
    status_now = client.get("/api/attendance/me/status", headers=login(STEWARD)).json()
    assert [r["shift"] for r in status_now["rostered_today"]] == ["Night"]                              # shown once, as the shift they are on
    r = client.post("/api/attendance/check-in", json={"location_id": loc_id(db, "MK")}, headers=login(STEWARD))
    assert r.status_code == 201
    assert r.json()["local_date"] == "2026-03-02" and r.json()["late_minutes"] == 450 and r.json()["shift_id"] == night.id   # Monday's shift, 7.5 h late
    clock.set(2026, 3, 3, 2, 0)
    days = {}
    for win in metrics.windows(db, clock.now, None, loc_id(db, "MK"), datetime(2026, 3, 2).date(), datetime(2026, 3, 3).date()):
        days.update({row["day"].isoformat(): row["status"] for row in metrics.attendance_stats(db, win, clock.now, emp.id)["rows"]})
    assert days["2026-03-02"] != "absent"                                                                # Monday is not a false absence


def test_check_in_before_the_evening_start_still_belongs_to_that_evenings_shift(client, login, db, clock):
    night_roster(db)
    clock.set(2026, 3, 3, 12, 0)                                           # 16:00 Dubai on Tuesday, an hour before the shift
    r = client.post("/api/attendance/check-in", json={"location_id": loc_id(db, "MK")}, headers=login(STEWARD))
    assert r.json()["local_date"] == "2026-03-03" and r.json()["late_minutes"] == 0
