from sqlalchemy import select

from app.models import AttendanceRecord, AuditLog

from .helpers import MGR, STEWARD, SUP, loc_id
from .test_absences import emp_id, login_mgr
from .test_attendance import check_in


def face(base=0.0):
    return [round(base + i * 0.001, 6) for i in range(128)]


def enroll(client, login, descriptor, code="E004"):
    return client.post(f"/api/employees/{emp_id(client, login_mgr(client), code)}/face", json={"descriptor": descriptor}, headers=login(MGR))


def turn_on(client, login, limit=45, live=0):
    values = {"attendance.face_required": 1, "attendance.face_match_max": limit, "attendance.face_liveness": live}
    return client.put("/api/settings", json={"values": values}, headers=login(MGR))


def test_only_a_manager_enrolls_a_valid_template_and_it_is_never_returned(client, login, db, clock):
    sid = emp_id(client, login_mgr(client), "E004")
    assert client.post(f"/api/employees/{sid}/face", json={"descriptor": face()}, headers=login(SUP)).status_code == 403
    assert client.post(f"/api/employees/{sid}/face", json={"descriptor": [0.1] * 127}, headers=login(MGR)).status_code == 422
    assert client.post(f"/api/employees/{sid}/face", json={"descriptor": [50.0] * 128}, headers=login(MGR)).status_code == 400
    made = enroll(client, login, face())
    assert made.status_code == 200 and made.json()["face_enrolled"] is True and "descriptor" not in made.text
    assert all("descriptor" not in str(a.after) for a in db.scalars(select(AuditLog).where(AuditLog.action == "employee.face_enroll")))
    assert client.delete(f"/api/employees/{sid}/face", headers=login(MGR)).json()["face_enrolled"] is False


def test_check_in_and_out_need_a_matching_face_when_the_setting_is_on(client, login, db, clock):
    h = login(STEWARD)
    assert check_in(client, h, db).status_code == 201                      # setting off: no face needed
    client.post("/api/attendance/check-out", json={"exception_reason": "Testing the face check"}, headers=h)
    assert turn_on(client, login).status_code == 200
    assert check_in(client, h, db).status_code == 400                      # not enrolled yet
    assert enroll(client, login, face()).status_code == 200
    assert check_in(client, h, db).status_code == 400                      # no face sent
    assert check_in(client, h, db, face=face(0.5)).status_code == 403      # a different face
    assert check_in(client, h, db, face=face(0.001)).status_code == 201    # close to the enrolled face
    out = "/api/attendance/check-out"
    assert client.post(out, json={"exception_reason": "Testing the face check"}, headers=h).status_code == 400
    assert client.post(out, json={"face": face(0.5), "exception_reason": "Testing the face check"}, headers=h).status_code == 403
    assert client.post(out, json={"face": face(0.002), "exception_reason": "Testing the face check"}, headers=h).status_code == 200
    saved = db.scalars(select(AttendanceRecord).order_by(AttendanceRecord.id.desc())).first()
    assert 0 < saved.check_in_face < 0.45 and 0 < saved.check_out_face < 0.45


def test_the_face_settings_are_validated(client, login, db, clock):
    m = login(MGR)
    assert client.put("/api/settings", json={"values": {"attendance.face_required": 2}}, headers=m).status_code == 400
    assert client.put("/api/settings", json={"values": {"attendance.face_match_max": 5}}, headers=m).status_code == 400
    assert client.put("/api/settings", json={"values": {"attendance.face_match_max": 90}}, headers=m).status_code == 400
    assert client.get("/api/attendance/me/status", headers=login(STEWARD)).json()["face_required"] is False
