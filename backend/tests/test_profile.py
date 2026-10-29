from sqlalchemy import select

from app.models import AuditLog, Employee, Role, User
from app.security import hash_password

from .conftest import PASSWORD
from .helpers import STEWARD


def test_a_person_reads_only_their_own_profile(client, login):
    h = login(STEWARD)
    mine = client.get("/api/profile?employee_id=1&email=manager@example.test", headers=h).json()
    assert mine["email"] == STEWARD and mine["employee"]["code"] == "E004"
    assert mine["employee"]["supervisor"] == "Sam Supervisor" and mine["employee"]["locations"]
    assert mine["role_label"] and "password_hash" not in str(mine)


def test_phone_and_emergency_contact_can_be_changed_and_are_audited(client, login, db):
    h = login(STEWARD)
    r = client.put("/api/profile", json={"phone": " +965 5000  1234 ", "emergency_contact": "Sara,  +965 5000 5678"}, headers=h)
    assert r.status_code == 200
    assert r.json()["employee"]["phone"] == "+965 5000 1234" and r.json()["employee"]["emergency_contact"] == "Sara, +965 5000 5678"
    assert client.get("/api/profile", headers=h).json()["employee"]["phone"] == "+965 5000 1234"
    entry = db.scalars(select(AuditLog).where(AuditLog.action == "profile.update")).one()
    assert entry.entity == "employee"


def test_other_fields_cannot_be_changed_here(client, login, db):
    h = login(STEWARD)
    for field, value in (("job_title", "Chief"), ("email", "x@example.test"), ("role", "manager"), ("employee_code", "E999"), ("full_name", "Someone Else")):
        assert client.put("/api/profile", json={field: value}, headers=h).status_code == 422, field
    emp = db.scalar(select(Employee).where(Employee.employee_code == "E004"))
    assert (emp.job_title, emp.full_name) == ("Steward", "Sid Steward")


def test_a_bad_phone_number_is_refused(client, login):
    r = client.put("/api/profile", json={"phone": "call me maybe"}, headers=login(STEWARD))
    assert r.status_code == 422


def test_an_account_without_an_employee_record_cannot_save(client, db):
    role = db.scalar(select(Role).where(Role.name == "steward"))
    db.add(User(email="orphan@example.test", password_hash=hash_password(PASSWORD), role_id=role.id))
    db.commit()
    token = client.post("/api/auth/login", json={"email": "orphan@example.test", "password": PASSWORD}).json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/profile", headers=h).json()["employee"] is None
    assert client.put("/api/profile", json={"phone": "+965 5000 1234"}, headers=h).status_code == 404


def test_signing_out_other_devices_keeps_only_the_current_one(client, login, db):
    other = login(STEWARD)
    mine = login(STEWARD)
    assert client.get("/api/auth/me", headers=other).status_code == 200
    fresh = client.post("/api/auth/sign-out-others", headers=mine)
    assert fresh.status_code == 200
    assert client.get("/api/auth/me", headers=other).status_code == 401
    assert client.get("/api/auth/me", headers=mine).status_code == 401
    kept = {"Authorization": f"Bearer {fresh.json()['access_token']}"}
    assert client.get("/api/auth/me", headers=kept).status_code == 200
    assert db.scalars(select(AuditLog).where(AuditLog.action == "session.sign_out_others")).one().entity == "user"
