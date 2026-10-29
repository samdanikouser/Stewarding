from sqlalchemy import select

from app.models import AttendanceCorrection, AuditLog, Notification

from .helpers import MGR, STEWARD, SUP, loc_id
from .test_absences import day_row, emp_id, login_mgr

URL = "/api/attendance/manual"


def manual(client, h, db, day="2026-02-27", check_in="06:00", check_out="14:00", code="E004", loc="MK", reason="Forgot to punch, confirmed by supervisor"):
    body = {"employee_id": emp_id(client, login_mgr(client), code), "location_id": loc_id(db, loc), "day": day,
            "check_in_time": check_in, "check_out_time": check_out, "reason": reason}
    return client.post(URL, json=body, headers=h)


def test_manager_adds_a_missed_day_and_it_counts_as_present(client, login, db, clock):
    mgr = login(MGR)
    r = manual(client, mgr, db)
    assert r.status_code == 201
    rec = r.json()
    assert rec["local_date"] == "2026-02-27" and rec["open"] is False and rec["late_minutes"] == 0
    assert rec["payable_minutes"] == 480 and rec["exception_reason"].startswith("Manual entry by manager")
    listing = client.get("/api/attendance?employee_id=%d" % rec["employee_id"], headers=mgr).json()["items"]
    assert [i["id"] for i in listing] == [rec["id"]]
    doc = client.get("/api/reports/records/attendance?date_from=2026-02-27&date_to=2026-02-27", headers=mgr).json()
    sid = next(r_ for g in doc["groups"] for r_ in g["rows"] if r_["employee"] == "Sid Steward")
    assert sid["status"] == "Present" and sid["check_in"] == "06:00" and sid["check_out"] == "14:00" and sid["worked"] == "8:00"
    assert sid["note"].startswith("Manual entry by manager")
    assert dict(next(g for g in doc["groups"] if "Main Kitchen" in g["title"])["totals"])["Present"] >= 1
    stats = client.get("/api/reports/daily?anchor=2026-02-27&location_id=%d" % loc_id(db, "MK"), headers=mgr).json()
    section = next(s for s in stats["sections"] if s["id"] == "attendance")
    assert next(r_ for r_ in section["rows"] if r_["employee"] == "Sid Steward")["status"] == "present"


def test_late_arrival_overnight_shift_and_the_audit_trail(client, login, db, clock):
    mgr = login(MGR)
    assert manual(client, mgr, db, check_in="07:30", check_out="15:00").json()["late_minutes"] == 90
    overnight = manual(client, mgr, db, day="2026-02-26", check_in="22:00", check_out="06:00").json()
    assert overnight["payable_minutes"] == 480 and overnight["check_out_at"].startswith("2026-02-27T02:00")  # 06:00 Dubai next day
    corrections = db.scalars(select(AttendanceCorrection).where(AttendanceCorrection.attendance_id == overnight["id"])).all()
    assert {c.field for c in corrections} == {"check_in_at", "check_out_at"} and all(c.reason.startswith("Manual entry") for c in corrections)
    assert db.scalar(select(AuditLog.id).where(AuditLog.action == "attendance.manual"))
    note = db.scalar(select(Notification).where(Notification.kind == "attendance_manual"))
    assert note and "Forgot to punch" in note.body


def test_only_a_manager_can_enter_attendance_by_hand(client, login, db, clock):
    for who in (SUP, STEWARD):
        assert manual(client, login(who), db).status_code == 403
    assert client.post(URL, json={}).status_code == 401


def test_manual_entries_are_validated(client, login, db, clock):
    mgr = login(MGR)
    assert manual(client, mgr, db, check_in="09:00", check_out="09:00").status_code == 400
    assert manual(client, mgr, db, day="2026-03-03").status_code == 400                      # tomorrow
    assert manual(client, mgr, db, day="2025-12-01").status_code == 400                      # too far back
    assert manual(client, mgr, db, day="2026-03-02", check_in="06:00", check_out="23:00").status_code == 400  # ends in the future
    assert manual(client, mgr, db, check_in="06:00", check_out="05:59").status_code == 400  # a 24 hour shift
    assert manual(client, mgr, db, reason="no").status_code == 422
    assert manual(client, mgr, db, code="E006", loc="MK").status_code == 400                  # works at the rooftop bar only
    assert manual(client, mgr, db).status_code == 201
    assert manual(client, mgr, db).status_code == 409                                         # already recorded that day


def test_an_absence_must_be_cancelled_before_attendance_is_entered(client, login, db, clock):
    mgr = login(MGR)
    body = {"employee_id": emp_id(client, mgr, "E004"), "location_id": loc_id(db, "MK"), "day": "2026-02-27", "absence_type": "absent"}
    absence = client.post("/api/absences", json=body, headers=mgr).json()
    assert manual(client, mgr, db).status_code == 409
    client.post(f"/api/absences/{absence['id']}/void", json={"reason": "Worked after all"}, headers=mgr)
    assert manual(client, mgr, db).status_code == 201


def test_a_record_entered_in_error_is_removed_with_a_reason_and_kept_in_the_audit_log(client, login, db, clock):
    mgr = login(MGR)
    rec = manual(client, mgr, db).json()
    url = f"/api/attendance/{rec['id']}/remove"
    assert client.post(url, json={"reason": "oops"}, headers=mgr).status_code == 422
    assert client.post(url, json={"reason": "Entered for the wrong day"}, headers=login(SUP)).status_code == 403
    assert client.post(url, json={"reason": "Entered for the wrong day"}, headers=login(STEWARD)).status_code == 403
    assert client.post(url, json={"reason": "Entered for the wrong day"}, headers=mgr).json() == {"deleted": rec["id"]}
    assert client.get("/api/attendance?employee_id=%d" % rec["employee_id"], headers=mgr).json()["items"] == []
    assert not db.scalars(select(AttendanceCorrection).where(AttendanceCorrection.attendance_id == rec["id"])).all()
    entry = db.scalars(select(AuditLog).where(AuditLog.action == "attendance.delete")).one()
    assert entry.before["date"] == "2026-02-27" and entry.after == {"reason": "Entered for the wrong day"}
    assert client.post(url, json={"reason": "Entered for the wrong day"}, headers=mgr).status_code == 404


def test_a_punch_record_can_be_changed_to_a_day_off(client, login, db, clock):
    mgr = login(MGR)
    rec = manual(client, mgr, db).json()
    r = client.post(f"/api/attendance/{rec['id']}/day-off", json={"reason": "Was on his day off"}, headers=mgr)
    assert r.status_code == 200
    assert client.get("/api/attendance?employee_id=%d" % rec["employee_id"], headers=mgr).json()["items"] == []
    days = client.get(f"/api/absences?employee_id={rec['employee_id']}", headers=mgr).json()["items"]
    assert [(d["local_date"], d["absence_type"]) for d in days] == [("2026-02-27", "day_off")]
    assert db.scalar(select(AuditLog.id).where(AuditLog.action == "attendance.to_day_off")) is not None
    assert client.post(f"/api/attendance/{rec['id']}/day-off", json={"reason": "Was on his day off"}, headers=mgr).status_code == 404


def test_working_at_another_outlet_is_not_absent_where_the_person_was_rostered(client, login, db, clock):
    from datetime import date, datetime

    from app.models import AttendanceRecord

    mgr = login(MGR)
    clock.set(2026, 3, 2, 12, 0)
    eid = emp_id(client, login_mgr(client), "E004")
    before = day_row(client, mgr, db)
    db.add(AttendanceRecord(employee_id=eid, location_id=loc_id(db, "RB"), local_date=date(2026, 3, 2),
                            check_in_at=datetime(2026, 3, 2, 6, 0), check_out_at=datetime(2026, 3, 2, 10, 0), payable_minutes=240))
    db.commit()
    after = day_row(client, mgr, db)
    assert before["elsewhere"] is None and after["elsewhere"] == "Rooftop Bar"
    url = f"/api/reports/records/attendance?date_from=2026-03-02&date_to=2026-03-02&location_id={loc_id(db, 'MK')}"
    rows = [r for g in client.get(url, headers=mgr).json()["groups"] for r in g["rows"] if r["employee"] == "Sid Steward"]
    assert [r["status"] for r in rows] == ["Worked elsewhere"] and rows[0]["note"] == "Worked at Rooftop Bar"


def test_a_punch_older_than_the_leave_window_cannot_be_changed_to_a_day_off(client, login, db, clock):
    from datetime import date, datetime

    from app.models import AttendanceRecord

    mgr = login(MGR)
    eid = emp_id(client, login_mgr(client), "E004")
    old = AttendanceRecord(employee_id=eid, location_id=loc_id(db, "MK"), local_date=date(2026, 1, 1),
                           check_in_at=datetime(2026, 1, 1, 6, 0), check_out_at=datetime(2026, 1, 1, 14, 0), payable_minutes=480)
    db.add(old)
    db.commit()
    assert client.post(f"/api/attendance/{old.id}/day-off", json={"reason": "Was on his day off"}, headers=mgr).status_code == 400
