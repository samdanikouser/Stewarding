from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import settings
from app.main import app
from app.models import Employee, User

from .conftest import PASSWORD
from .helpers import MGR, STEWARD, STEWARD_RB, SUP, SUP_RB, item_id, loc_id

PUBLIC = {("POST", "/api/auth/login"), ("POST", "/api/auth/signup"),("GET", "/api/health"), ("GET", "/api/organization/public"), ("GET", "/api/organization/logo"),
          ("GET", "/api/training/media/{token}")}  # a player cannot send headers, so this link is signed and short-lived instead


def api_routes():
    """Every method and path the app really serves, read from its OpenAPI schema."""
    for path, operations in app.openapi()["paths"].items():
        if path.startswith("/api"):
            for method in operations:
                yield method.upper(), path


def concrete(path: str) -> str:
    out = path
    while "{" in out:
        start, end = out.index("{"), out.index("}")
        out = out[:start] + "1" + out[end + 1:]
    return out


def test_every_protected_route_rejects_anonymous_requests(client):
    routes = [(m, p) for m, p in api_routes() if (m, p) not in PUBLIC]
    assert len(routes) > 80  # guards against the enumeration silently returning nothing
    for method, path in routes:
        r = client.request(method, concrete(path), json={} if method in ("POST", "PUT") else None)
        assert r.status_code == 401, f"{method} {path} answered {r.status_code} without a token"


def test_every_protected_route_rejects_a_garbage_token(client):
    for method, path in [(m, p) for m, p in api_routes() if (m, p) not in PUBLIC][:40]:
        r = client.request(method, concrete(path), headers={"Authorization": "Bearer not-a-token"})
        assert r.status_code == 401


MANAGER_ONLY = [
    ("POST", "/api/employees", {}), ("PUT", "/api/employees/1", {}), ("POST", "/api/employees/1/deactivate", None),
    ("POST", "/api/roster/shifts", {}), ("POST", "/api/roster/assignments", {}),
    ("POST", "/api/attendance/1/correct", {}), ("POST", "/api/attendance/manual", {}), ("POST", "/api/employees/1/reset-password", {}), ("POST", "/api/checklists/templates", {}),
    ("POST", "/api/checklists/generate", {}), ("POST", "/api/equipment", {}), ("PUT", "/api/equipment/1", {}),
    ("PUT", "/api/equipment/schedules/1", {}), ("POST", "/api/inventory/items", {}), ("POST", "/api/inventory/categories", {}),
    ("POST", "/api/inventory/units", {}), ("POST", "/api/inventory/assets", {}), ("POST", "/api/stock/transfers/1/decision", {}),
    ("POST", "/api/breakage/1/approve", {}), ("GET", "/api/settings", None), ("PUT", "/api/settings", {}),
    ("POST", "/api/settings/locations", {}), ("GET", "/api/audit", None), ("GET", "/api/reports/daily/export", None), ("GET", "/api/reports/records/monitoring/export", None),
    ("POST", "/api/suppliers", {}), ("PUT", "/api/suppliers/1", {}), ("PUT", "/api/inventory/categories/1", {}),
    ("PUT", "/api/inventory/units/1", {}), ("POST", "/api/lookups", {}), ("PUT", "/api/lookups/1", {}),
    ("POST", "/api/receipts/1/void", {"reason": "Entered by mistake"}),
    ("GET", "/api/equipment/templates", None), ("PUT", "/api/organization", {"name": "Test Org"}), ("POST", "/api/organization/logo", None), ("DELETE", "/api/organization/logo", None), ("POST", "/api/equipment/from-template", {}), ("POST", "/api/equipment/forms", {}),
]

SUPERVISOR_UP = [
    ("GET", "/api/employees", None), ("GET", "/api/attendance", None), ("GET", "/api/roster/today?location_id=1", None),
    ("GET", "/api/reports/daily", None), ("GET", "/api/reports/records/monitoring", None), ("GET", "/api/reports/records/checklists", None), ("GET", "/api/notifications/pending-summary", None),
    ("GET", "/api/absences", None), ("POST", "/api/absences", {}), ("POST", "/api/absences/1/void", {"reason": "Entered by mistake"}),
    ("POST", "/api/stock/transfers", {}), ("POST", "/api/stock/counts", {}), ("GET", "/api/breakage", None),
    ("POST", "/api/breakage/1/review", {"qty": 1}), ("POST", "/api/checklists/instances/1/verify", {"approve": True}),
    ("POST", "/api/checklists/instances/1/assign", {"employee_id": 1}), ("POST", "/api/inventory/transactions", {}),
    ("POST", "/api/monitoring/readings/1/review", None), ("GET", "/api/equipment", None),
    ("POST", "/api/receipts", {}), ("GET", "/api/receipts", None), ("GET", "/api/receipts/1", None),
    ("GET", "/api/suppliers", None),
]


@pytest.mark.parametrize("method,path,body", MANAGER_ONLY)
def test_manager_only_endpoints_are_forbidden_to_everyone_else(client, login, method, path, body):
    for who in (STEWARD, SUP):
        r = client.request(method, path, json=body, headers=login(who))
        assert r.status_code == 403, f"{who} reached {method} {path}"
    assert client.request(method, path, json=body, headers=login(MGR)).status_code != 403


@pytest.mark.parametrize("method,path,body", SUPERVISOR_UP)
def test_supervisor_endpoints_are_forbidden_to_stewards(client, login, method, path, body):
    assert client.request(method, path, json=body, headers=login(STEWARD)).status_code == 403
    assert client.request(method, path, json=body, headers=login(SUP)).status_code != 403


LOCATION_SCOPED = [
    "/api/attendance?location_id={mk}", "/api/employees?location_id={mk}", "/api/roster/today?location_id={mk}",
    "/api/roster/assignments?location_id={mk}", "/api/checklists/templates?location_id={mk}",
    "/api/checklists/instances?location_id={mk}", "/api/equipment?location_id={mk}",
    "/api/monitoring/equipment?location_id={mk}", "/api/monitoring/due?location_id={mk}",
    "/api/monitoring/readings?location_id={mk}", "/api/reports/records/monitoring?location_id={mk}", "/api/monitoring/corrective-actions?location_id={mk}",
    "/api/inventory/items?location_id={mk}", "/api/inventory/transactions?location_id={mk}",
    "/api/inventory/assets?location_id={mk}", "/api/stock/counts?location_id={mk}",
    "/api/stock/reconciliation?month=2026-03&location_id={mk}", "/api/breakage?location_id={mk}",
    "/api/reports/daily?location_id={mk}", "/api/dashboard?location_id={mk}",
    "/api/notifications/pending-summary?location_id={mk}",
]


@pytest.mark.parametrize("template", LOCATION_SCOPED)
def test_staff_at_another_location_cannot_read_main_kitchen_data(client, login, db, template):
    path = template.format(mk=loc_id(db, "MK"))
    for who in (SUP_RB, STEWARD_RB):
        assert client.get(path, headers=login(who)).status_code == 403, f"{who} read {path}"
    assert client.get(path, headers=login(MGR)).status_code == 200


def test_lists_without_a_location_never_leak_other_locations(client, login, db, clock):
    client.post("/api/checklists/generate", json={"location_id": loc_id(db, "MK")}, headers=login(MGR))
    client.post("/api/attendance/check-in", json={"location_id": loc_id(db, "MK")}, headers=login(STEWARD))
    client.post("/api/breakage", headers=login(STEWARD), json={"location_id": loc_id(db, "MK"), "item_id": item_id(db, "PL-001"),
                                                                 "qty": 1, "incident_type": "breakage"})
    rb = loc_id(db, "RB")
    h = login(SUP_RB)
    assert all(i["location_id"] == rb for i in client.get("/api/checklists/instances?size=200", headers=h).json()["items"])
    assert client.get("/api/attendance", headers=h).json()["total"] == 0
    assert client.get("/api/breakage", headers=h).json()["total"] == 0
    assert all(rb in e["location_ids"] for e in client.get("/api/employees?size=100", headers=h).json()["items"])
    assert {e["location_id"] for e in client.get("/api/equipment", headers=h).json()} == {rb}
    assert {i["location"] for i in client.get("/api/notifications/pending-summary", headers=h).json()["items"]} <= {"Rooftop Bar"}


def test_token_tampering_expiry_and_foreign_keys_are_rejected(client, login, db):
    valid = login(STEWARD)["Authorization"].split()[1]
    user_id = int(jwt.decode(valid, options={"verify_signature": False})["sub"])

    def status(token):
        return client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code

    assert status(valid) == 200
    assert status(valid[:-3] + ("AAA" if not valid.endswith("AAA") else "BBB")) == 401
    expired = jwt.encode({"sub": str(user_id), "exp": datetime.now(timezone.utc) - timedelta(minutes=1)}, settings.secret_key, "HS256")
    assert status(expired) == 401
    forged = jwt.encode({"sub": str(user_id), "exp": datetime.now(timezone.utc) + timedelta(hours=1)}, "x" * 40, "HS256")
    assert status(forged) == 401
    none_alg = jwt.encode({"sub": str(user_id)}, "", algorithm="none")
    assert status(none_alg) == 401
    missing_user = jwt.encode({"sub": "99999", "exp": datetime.now(timezone.utc) + timedelta(hours=1)}, settings.secret_key, "HS256")
    assert status(missing_user) == 401


def test_passwords_are_hashed_and_never_returned(client, login, db):
    for user in db.scalars(select(User)):
        assert user.password_hash.startswith("$2") and PASSWORD not in user.password_hash
    me = client.get("/api/auth/me", headers=login(MGR))
    assert "password" not in me.text and "$2" not in me.text
    listing = client.get("/api/employees", headers=login(MGR))
    assert "password" not in listing.text and "$2" not in listing.text


def test_user_input_is_never_executed_as_sql(client, login):
    h = login(MGR)
    for payload in ("' OR 1=1 --", "'; DROP TABLE employee; --", "%' UNION SELECT password_hash FROM user --"):
        r = client.get("/api/employees", params={"search": payload}, headers=h)
        assert r.status_code == 200 and r.json()["items"] == []
        assert client.get("/api/inventory/items", params={"search": payload}, headers=h).json()["items"] == []
    assert client.get("/api/employees", headers=h).json()["total"] == 6


def test_cannot_mass_assign_status_or_role_through_updates(client, login, db):
    h = login(MGR)
    emp = next(e for e in client.get("/api/employees", headers=h).json()["items"] if e["employee_code"] == "E004")
    r = client.put(f"/api/employees/{emp['id']}", json={"job_title": "Lead", "status": "inactive", "user_id": 1, "id": 99}, headers=h)
    assert r.status_code == 200 and r.json()["status"] == "active" and r.json()["id"] == emp["id"]
    assert db.scalar(select(Employee.user_id).where(Employee.id == emp["id"])) != 1


def test_uploads_are_validated_by_content_size_and_name(client, login):
    h = login(STEWARD)
    html = client.post("/api/uploads", files={"file": ("evil.png", b"<html><script>alert(1)</script></html>", "image/png")}, headers=h)
    assert html.status_code == 415
    big = client.post("/api/uploads", files={"file": ("big.png", b"\x89PNG\r\n\x1a\n" + b"0" * (5 * 1024 * 1024 + 10), "image/png")}, headers=h)
    assert big.status_code == 413
    ok = client.post("/api/uploads", files={"file": ("../../etc/passwd.png", b"\x89PNG\r\n\x1a\n" + b"0" * 16, "image/png")}, headers=h)
    assert ok.status_code == 201 and ok.json()["name"].endswith(".png") and "/" not in ok.json()["name"]
    for name in ("..%2f..%2fetc%2fpasswd", "../secret", "x.exe", "A" * 32 + ".png"):
        assert client.get(f"/api/uploads/{name}", headers=h).status_code == 404
    assert client.get(f"/api/uploads/{ok.json()['name']}").status_code == 401


def test_app_refuses_to_start_without_a_strong_secret(monkeypatch):
    monkeypatch.setattr(settings, "secret_key", "short")
    with pytest.raises(RuntimeError, match="STW_SECRET_KEY"):
        with TestClient(app):
            pass


def test_login_and_error_responses_do_not_reveal_which_part_was_wrong(client):
    unknown = client.post("/api/auth/login", json={"email": "ghost@example.test", "password": "x"})
    wrong = client.post("/api/auth/login", json={"email": MGR, "password": "x"})
    assert unknown.status_code == wrong.status_code == 401 and unknown.json() == wrong.json()
    assert client.get("/api/does-not-exist").status_code == 404
