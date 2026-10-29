from sqlalchemy import select

from app.models import AuditLog, Role, User
from app.permissions import ALL_PERMISSIONS
from app.seed import sync_roles
from app.services.notify import recipients

from .helpers import MGR, STEWARD, SUP, loc_id

CHEF_PASSWORD = "Kitchen-pass-9876!"


def make_role(client, h, label="Head Chef", tier="supervisor", permissions=None):
    perms = permissions if permissions is not None else ["dashboard.view", "inventory.module", "inventory.view", "inventory.count", "report.view"]
    return client.post("/api/roles", headers=h, json={"label": label, "tier": tier, "permissions": perms})


def hire(client, db, h, role, email, places=("MK",), **extra):
    body = {"full_name": "Test Person", "job_title": "Head Chef", "email": email, "password": CHEF_PASSWORD, "role": role,
            "location_ids": [loc_id(db, p) for p in places], **extra}
    made = client.post("/api/employees", headers=h, json=body)
    assert made.status_code == 201, made.text
    db.expire_all()
    db.scalar(select(User).where(User.email == email)).must_change_password = False
    db.commit()
    token = client.post("/api/auth/login", json={"email": email, "password": CHEF_PASSWORD}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_a_manager_makes_a_role_and_the_person_gets_exactly_those_permissions(client, login, db, clock):
    m = login(MGR)
    made = make_role(client, m)
    assert made.status_code == 201 and made.json()["name"] == "head_chef" and made.json()["label"] == "Head Chef"
    chef = hire(client, db, m, "head_chef", "chef@example.com")
    assert client.get("/api/inventory/items", headers=chef).status_code == 200
    assert client.post("/api/employees", headers=chef, json={}).status_code == 403
    assert client.get("/api/roles", headers=chef).status_code == 403
    me = client.get("/api/auth/me", headers=chef).json()
    assert me["tier"] == "supervisor" and me["role_label"] == "Head Chef" and "settings.manage" not in me["permissions"]
    assert {mod["key"] for mod in me["modules"]} >= {"inventory", "reports"} and "settings" not in {mod["key"] for mod in me["modules"]}


def test_only_a_manager_can_change_roles(client, login, db, clock):
    for who in (SUP, STEWARD):
        assert make_role(client, login(who)).status_code == 403
    assert client.get("/api/roles/catalog", headers=login(SUP)).status_code == 403


def test_a_role_is_checked_before_it_is_saved(client, login, db, clock):
    m = login(MGR)
    assert make_role(client, m, permissions=["not.a.permission"]).status_code == 422
    assert make_role(client, m, tier="manager").status_code == 422
    assert make_role(client, m, permissions=[]).status_code == 422
    assert make_role(client, m).status_code == 201
    assert make_role(client, m, label="head chef").status_code == 409
    assert make_role(client, m, label="Supervisor").status_code == 409


def test_the_supervisor_and_steward_roles_can_be_edited_and_keep_the_edit_but_not_the_manager(client, login, db, clock):
    m = login(MGR)
    manager = db.scalar(select(Role).where(Role.name == "manager"))
    supervisor = db.scalar(select(Role).where(Role.name == "supervisor"))
    assert client.put(f"/api/roles/{manager.id}", headers=m, json={"label": "Boss"}).status_code == 400
    assert client.put(f"/api/roles/{supervisor.id}", headers=m, json={"tier": "steward"}).status_code == 400
    edited = client.put(f"/api/roles/{supervisor.id}", headers=m, json={"label": "Shift Lead", "permissions": ["dashboard.view", "breakage.view"]})
    assert edited.status_code == 200 and edited.json()["permissions"] == ["breakage.view", "dashboard.view"] and edited.json()["builtin"]
    sync_roles(db)                                                       # what every start-up runs
    db.commit()
    db.expire_all()
    kept = db.scalar(select(Role).where(Role.name == "supervisor"))
    assert kept.label == "Shift Lead" and sorted(p.permission for p in kept.permissions) == ["breakage.view", "dashboard.view"]
    assert len(db.scalar(select(Role).where(Role.name == "manager")).permissions) == len(ALL_PERMISSIONS)
    assert client.delete(f"/api/roles/{supervisor.id}", headers=m).status_code == 400


def test_a_role_in_use_cannot_be_deleted(client, login, db, clock):
    m = login(MGR)
    role = make_role(client, m).json()
    hire(client, db, m, role["name"], "chef@example.com")
    assert client.delete(f"/api/roles/{role['id']}", headers=m).status_code == 409
    spare = make_role(client, m, label="Spare Role").json()
    assert client.delete(f"/api/roles/{spare['id']}", headers=m).status_code == 200
    actions = {a.action for a in db.scalars(select(AuditLog))}
    assert {"role.create", "role.delete"} <= actions


def test_changing_a_role_changes_what_its_people_may_do(client, login, db, clock):
    m = login(MGR)
    role = make_role(client, m).json()
    chef = hire(client, db, m, role["name"], "chef@example.com")
    assert client.get("/api/breakage", headers=chef).status_code == 403
    changed = client.put(f"/api/roles/{role['id']}", headers=m, json={"permissions": ["dashboard.view", "breakage.view"]})
    assert changed.status_code == 200 and changed.json()["users"] == 1
    assert client.get("/api/breakage", headers=chef).status_code == 200
    assert client.get("/api/inventory/items", headers=chef).status_code == 403


def test_the_tier_decides_who_is_told_and_what_they_see(client, login, db, clock):
    m = login(MGR)
    make_role(client, m)
    make_role(client, m, label="Kitchen Porter", tier="steward", permissions=["dashboard.view", "attendance.self", "checklist.view"])
    chef = hire(client, db, m, "head_chef", "chef@example.com", places=("BQ",))
    porter = hire(client, db, m, "kitchen_porter", "porter@example.com")
    chef_id = db.scalar(select(User.id).where(User.email == "chef@example.com"))
    assert chef_id in recipients(db, loc_id(db, "BQ"), "supervisor")
    assert chef_id not in recipients(db, loc_id(db, "RB"), "supervisor")
    assert client.get("/api/dashboard", headers=porter).json()["role"] == "steward"
    assert client.get("/api/dashboard", headers=chef).json().get("role") != "steward"


def test_nobody_can_hand_out_more_access_than_they_hold(client, login, db, clock):
    m = login(MGR)
    make_role(client, m, label="Hr Lead", permissions=["dashboard.view", "employee.view", "employee.manage"])
    make_role(client, m, label="Boss Light", permissions=["dashboard.view", "settings.manage"])
    hr = hire(client, db, m, "hr_lead", "hr@example.com")
    sent = {"full_name": "New Hire", "job_title": "Cook", "email": "new@example.com", "password": CHEF_PASSWORD,
            "location_ids": [loc_id(db, "MK")]}
    assert client.post("/api/employees", headers=hr, json={**sent, "role": "manager"}).status_code == 403
    assert client.post("/api/employees", headers=hr, json={**sent, "role": "boss_light"}).status_code == 403
    assert client.post("/api/employees", headers=hr, json={**sent, "role": "nonexistent"}).status_code == 400
    assert client.post("/api/employees", headers=hr, json={**sent, "role": "steward"}).status_code == 403   # steward holds permissions the HR lead does not
    names = {o["name"] for o in client.get("/api/roles/options", headers=hr).json()}
    assert "manager" not in names and "boss_light" not in names and "hr_lead" in names
    assert {"manager", "supervisor", "steward", "hr_lead", "boss_light"} <= {o["name"] for o in client.get("/api/roles/options", headers=m).json()}


def test_the_dashboard_shows_only_the_parts_a_role_may_open(client, login, db, clock):
    m = login(MGR)
    make_role(client, m, label="Stock Viewer", permissions=["dashboard.view", "inventory.module"])
    viewer = hire(client, db, m, "stock_viewer", "stock@example.com")
    seen = client.get("/api/dashboard", headers=viewer).json()
    assert seen["sections"] == ["stock"] and seen["approvals"] == []
    assert seen["charts"]["attendance_trend"] == [] and seen["charts"]["task_trend"] == [] and seen["charts"]["monitoring_compliance"] == []
    assert seen["kpis"]["scheduled_today"] == 0 and seen["kpis"]["daily_completion"]["denominator"] == 0
    assert {i["category"] for i in seen["supervisor"]["pending"]["items"]} <= {"low_stock", "transfer"}
    assert seen["supervisor"]["staff_today"] == []
    full = client.get("/api/dashboard", headers=m).json()
    assert full["sections"] == ["people", "checklists", "monitoring", "stock", "breakage"] and full["approvals"] == ["tasks", "readings", "breakage"]
    assert full["charts"]["attendance_trend"]


def test_approval_alerts_reach_every_role_that_may_approve_not_only_managers(client, login, db, clock):
    from app.models import Notification
    m = login(MGR)
    make_role(client, m, label="Store Approver", permissions=["dashboard.view", "inventory.module", "stock.transfer", "stock.approve"])
    make_role(client, m, label="Store Clerk", permissions=["dashboard.view", "inventory.module", "stock.transfer"])
    hire(client, db, m, "store_approver", "approver@example.com", places=("MK",))
    hire(client, db, m, "store_clerk", "clerk@example.com", places=("MK",))
    far = hire(client, db, m, "store_approver", "faraway@example.com", places=("RB",))
    sup = login(SUP)
    sent = client.post("/api/stock/transfers", headers=sup, json={"from_location_id": loc_id(db, "MK"), "to_location_id": loc_id(db, "BQ"),
                                                                  "lines": [{"item_id": 1, "qty": 1}]})
    assert sent.status_code == 201 and sent.json()["status"] == "requested"
    told = {db.scalar(select(User.email).where(User.id == n.user_id)) for n in db.scalars(select(Notification).where(Notification.kind == "transfer_pending"))}
    assert told == {MGR, "approver@example.com"}
    assert far and "clerk@example.com" not in told and "faraway@example.com" not in told


def test_built_in_roles_report_their_default_permissions_so_an_edit_can_be_undone(client, login, db, clock):
    m = login(MGR)
    listed = {r["name"]: r for r in client.get("/api/roles", headers=m).json()}
    assert listed["steward"]["defaults"] and "attendance.self" in listed["steward"]["defaults"]
    made = make_role(client, m).json()
    assert made["defaults"] is None
    client.put(f"/api/roles/{listed['steward']['id']}", headers=m, json={"permissions": ["dashboard.view"]})
    changed = {r["name"]: r for r in client.get("/api/roles", headers=m).json()}["steward"]
    assert changed["permissions"] == ["dashboard.view"] and changed["defaults"] == listed["steward"]["defaults"]


def apply_head_chef_migration(db):
    import importlib.util, pathlib
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path = pathlib.Path(__file__).parent.parent / "alembic" / "versions" / "p0d4f8b2e6a9_head_chef_role.py"
    spec = importlib.util.spec_from_file_location("head_chef", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with Operations.context(MigrationContext.configure(db.connection())):
        module.upgrade()
    db.commit()
    db.expire_all()


def test_the_head_chef_role_approves_monitoring_and_sees_nothing_of_stock_staff_or_pay(client, login, db, clock):
    apply_head_chef_migration(db)
    apply_head_chef_migration(db)                                                    # running it again changes nothing
    assert db.scalars(select(Role).where(Role.name == "head_chef")).all().__len__() == 1
    chef = hire(client, db, login(MGR), "head_chef", "headchef@example.com")
    for url in ("/api/monitoring/due", "/api/monitoring/readings", "/api/monitoring/corrective-actions", "/api/checklists/instances", "/api/notifications"):
        assert client.get(url, headers=chef).status_code == 200, url
    assert client.post("/api/monitoring/readings/review", json={"reading_ids": [999]}, headers=chef).status_code == 200   # may approve logs
    assert client.post("/api/monitoring/corrective-actions/999/decision", json={"decision": "approve"}, headers=chef).status_code != 403
    for url in ("/api/inventory/items", "/api/employees", "/api/attendance", "/api/roster/assignments", "/api/stock/insights",
                "/api/reports/catalog", "/api/roles", "/api/settings", "/api/breakage"):
        assert client.get(url, headers=chef).status_code == 403, url
    modules = {m["key"] for m in client.get("/api/auth/me", headers=chef).json()["modules"]}
    assert modules == {"dashboard", "checklists", "monitoring", "training", "tasks"}
