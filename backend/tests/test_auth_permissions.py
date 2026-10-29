import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import get_db
from app.deps import check_location, require
from app.models import Employee, Location, User
from app.permissions import MODULES

from .conftest import PASSWORD

# A throwaway app that exposes the real dependencies, so each rule is tested directly.
probe = FastAPI()


@probe.get("/settings")
def settings_probe(user: User = Depends(require("settings.manage"))):
    return {"ok": True}


@probe.get("/location/{location_id}")
def location_probe(location_id: int, user: User = Depends(require("checklist.view")), db=Depends(get_db)):
    check_location(user, db, location_id)
    return {"ok": True}


def probe_client(login, email):
    c = TestClient(probe)
    c.headers.update(login(email))
    return c


def location_id(db, code):
    return db.scalar(select(Location.id).where(Location.code == code))


@pytest.mark.parametrize("email,role", [
    ("manager@example.test", "manager"),
    ("sup.mk@example.test", "supervisor"),
    ("steward.mk@example.test", "steward"),
])
def test_each_role_can_sign_in(client, login, email, role):
    r = client.get("/api/auth/me", headers=login(email))
    assert r.status_code == 200
    assert r.json()["role"] == role


def test_bad_credentials_rejected(client):
    assert client.post("/api/auth/login", json={"email": "manager@example.test", "password": "wrong"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "nobody@example.test", "password": PASSWORD}).status_code == 401


def test_protected_route_needs_token(client):
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer junk"}).status_code == 401


def test_navigation_is_limited_by_role(client, login):
    def keys(email):
        return {m["key"] for m in client.get("/api/auth/me", headers=login(email)).json()["modules"]}

    assert keys("manager@example.test") == {k for k, _, _ in MODULES}
    sup = keys("sup.mk@example.test")
    assert "reports" in sup and not {"settings", "audit"} & sup
    assert "inventory" in sup
    steward = keys("steward.mk@example.test")
    assert {"check-in", "attendance"} <= steward and not {"employees", "reports", "settings", "audit", "roster", "inventory", "stock-movements"} & steward


def test_permission_enforced_on_server(login):
    assert probe_client(login, "manager@example.test").get("/settings").status_code == 200
    assert probe_client(login, "sup.mk@example.test").get("/settings").status_code == 403
    assert probe_client(login, "steward.mk@example.test").get("/settings").status_code == 403


def test_supervisor_cannot_reach_unassigned_location(login, db):
    sup_mk = probe_client(login, "sup.mk@example.test")
    assert sup_mk.get(f"/location/{location_id(db, 'MK')}").status_code == 200
    assert sup_mk.get(f"/location/{location_id(db, 'RB')}").status_code == 403
    assert sup_mk.get("/location/9999").status_code == 404


def test_steward_scoped_to_own_location_and_manager_sees_all(client, login, db):
    steward = client.get("/api/auth/me", headers=login("steward.rb@example.test")).json()
    assert [loc["code"] for loc in steward["locations"]] == ["RB"]
    manager = client.get("/api/auth/me", headers=login("manager@example.test")).json()
    assert {loc["code"] for loc in manager["locations"]} == {"MK", "BQ", "RB"}
    assert probe_client(login, "manager@example.test").get(f"/location/{location_id(db, 'RB')}").status_code == 200


def test_inactive_employee_cannot_sign_in_and_token_dies(client, login, db):
    headers = login("steward.mk@example.test")
    emp = db.scalar(select(Employee).where(Employee.employee_code == "E004"))
    emp.status = "inactive"
    db.commit()
    assert client.get("/api/auth/me", headers=headers).status_code == 401
    r = client.post("/api/auth/login", json={"email": "steward.mk@example.test", "password": PASSWORD})
    assert r.status_code == 401


def test_login_locks_after_repeated_failures(client):
    bad = {"email": "manager@example.test", "password": "wrong"}
    for _ in range(5):
        assert client.post("/api/auth/login", json=bad).status_code == 401
    assert client.post("/api/auth/login", json=bad).status_code == 429
    good = {"email": "manager@example.test", "password": PASSWORD}
    assert client.post("/api/auth/login", json=good).status_code == 429


def test_seed_is_idempotent(db):
    from app.seed import seed

    seed(db, PASSWORD)
    assert len(db.scalars(select(User)).all()) == 6


SIGNUP = {"full_name": "New Hire", "email": "new.hire@example.test", "password": "Fresh-Start-42"}


def test_signup_stays_pending_until_a_manager_approves(client, login, db):
    assert client.post("/api/auth/signup", json=SIGNUP).status_code == 202
    emp = db.scalar(select(Employee).where(Employee.email == SIGNUP["email"]))
    assert (emp.status, emp.user.active, emp.user.role.name) == ("pending", False, "steward")
    r = client.post("/api/auth/login", json={"email": SIGNUP["email"], "password": SIGNUP["password"]})
    assert r.status_code == 403 and "approve" in r.json()["detail"]
    manager = login("manager@example.test")
    assert client.post(f"/api/employees/{emp.id}/activate", headers=manager).status_code == 200
    r = client.post("/api/auth/login", json={"email": SIGNUP["email"], "password": SIGNUP["password"]})
    assert r.status_code == 200


def test_signup_rejects_weak_password_and_hides_existing_email(client, db):
    assert client.post("/api/auth/signup", json={**SIGNUP, "password": "short"}).status_code == 400
    before = len(db.scalars(select(User)).all())
    r = client.post("/api/auth/signup", json={**SIGNUP, "email": "manager@example.test"})
    assert r.status_code == 202
    assert len(db.scalars(select(User)).all()) == before
