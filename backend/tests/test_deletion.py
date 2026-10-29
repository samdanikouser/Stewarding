from datetime import date, datetime

from sqlalchemy import select

from app.models import AuditLog, InventoryItem, Supplier

from .helpers import MGR, STEWARD, SUP, loc_id


def test_an_unused_location_is_deleted_and_audited(client, login, db):
    m = login(MGR)
    made = client.post("/api/settings/locations", json={"code": "TMP", "name": "Temporary Site", "kind": "other", "timezone": "Asia/Kuwait"}, headers=m)
    assert made.status_code == 201
    gone = client.delete(f"/api/settings/locations/{made.json()['id']}", headers=m)
    assert gone.status_code == 200 and gone.json() == {"deleted": made.json()["id"]}
    assert all(loc["code"] != "TMP" for loc in client.get("/api/settings", headers=m).json()["locations"])
    entry = db.scalars(select(AuditLog).where(AuditLog.action == "location.delete")).one()
    assert entry.before == {"code": "TMP", "name": "Temporary Site"}


def test_a_location_in_use_is_refused_with_what_uses_it(client, login, db):
    m = login(MGR)
    r = client.delete(f"/api/settings/locations/{loc_id(db, 'MK')}", headers=m)
    assert r.status_code == 409 and "used by" in r.json()["detail"] and "make it inactive instead" in r.json()["detail"]
    assert client.delete("/api/settings/locations/99999", headers=m).status_code == 404


def test_only_managers_delete_settings_records(client, login, db):
    for email in (SUP, STEWARD):
        h = login(email)
        assert client.delete(f"/api/settings/locations/{loc_id(db, 'MK')}", headers=h).status_code == 403
        assert client.delete("/api/roster/shifts/1", headers=h).status_code == 403
        assert client.delete("/api/lookups/1", headers=h).status_code == 403


def test_an_unused_shift_is_deleted_but_one_with_assignments_is_not(client, login, db):
    m = login(MGR)
    body = {"name": "Split", "start_time": "09:00", "end_time": "17:00"}
    free = client.post("/api/roster/shifts", json=body, headers=m).json()
    assert client.delete(f"/api/roster/shifts/{free['id']}", headers=m).status_code == 200
    used = client.post("/api/roster/shifts", json={**body, "name": "Split two"}, headers=m).json()
    employee = client.get("/api/employees?size=1", headers=m).json()["items"][0]
    assigned = client.post("/api/roster/assignments", headers=m, json={
        "employee_id": employee["id"], "shift_id": used["id"], "location_id": employee["location_ids"][0], "weekdays": [2], "valid_from": "2030-01-01"})
    assert assigned.status_code == 201, assigned.text
    r = client.delete(f"/api/roster/shifts/{used['id']}", headers=m)
    assert r.status_code == 409 and "roster assignments" in r.json()["detail"]


def test_lists_categories_and_units_delete_when_unused(client, login):
    m = login(MGR)
    value = client.post("/api/lookups", json={"kind": "corrective_action", "value": "Move to the cold room"}, headers=m).json()
    assert client.delete(f"/api/lookups/{value['id']}", headers=m).status_code == 200
    category = client.post("/api/inventory/categories", json={"name": "Spare category"}, headers=m).json()
    assert client.delete(f"/api/inventory/categories/{category['id']}", headers=m).status_code == 200
    unit = client.post("/api/inventory/units", json={"name": "Spare unit"}, headers=m).json()
    assert client.delete(f"/api/inventory/units/{unit['id']}", headers=m).status_code == 200


def test_a_category_or_unit_that_items_use_is_refused(client, login, db):
    m = login(MGR)
    item = db.scalars(select(InventoryItem)).first()
    cat = client.delete(f"/api/inventory/categories/{item.category_id}", headers=m)
    unit = client.delete(f"/api/inventory/units/{item.unit_id}", headers=m)
    assert cat.status_code == 409 and "items" in cat.json()["detail"]
    assert unit.status_code == 409 and "items" in unit.json()["detail"]


def test_a_supplier_is_deleted_unless_items_use_it(client, login, db):
    m = login(MGR)
    free = client.post("/api/suppliers", json={"name": "Spare Supplier"}, headers=m).json()
    assert client.delete(f"/api/suppliers/{free['id']}", headers=m).status_code == 200
    used = client.post("/api/suppliers", json={"name": "Busy Supplier"}, headers=m).json()
    item = db.scalars(select(InventoryItem)).first()
    assert client.put(f"/api/inventory/items/{item.id}", json={"supplier_id": used["id"]}, headers=m).status_code == 200
    r = client.delete(f"/api/suppliers/{used['id']}", headers=m)
    assert r.status_code == 409 and "items" in r.json()["detail"]
    assert db.scalar(select(Supplier.id).where(Supplier.id == used["id"])) == used["id"]


def test_an_item_with_no_history_is_deleted_but_one_with_stock_is_not(client, login, db):
    m = login(MGR)
    item = db.scalars(select(InventoryItem)).first()
    fresh = client.post("/api/inventory/items", json={"name": "Spare Tray", "category_id": item.category_id, "unit_id": item.unit_id}, headers=m).json()
    assert client.delete(f"/api/inventory/items/{fresh['id']}", headers=m).status_code == 200
    r = client.delete(f"/api/inventory/items/{item.id}", headers=m)
    assert r.status_code == 409 and "make it inactive instead" in r.json()["detail"]


def new_employee(client, h, db, email, code=None):
    body = {"full_name": "Temp Person", "job_title": "Steward", "email": email, "password": "Temp-Pass-4242", "role": "steward",
            "location_ids": [loc_id(db, "MK")], **({"employee_code": code} if code else {})}
    made = client.post("/api/employees", json=body, headers=h)
    assert made.status_code == 201, made.text
    return made.json()


def test_an_employee_added_by_mistake_is_deleted_with_their_account(client, login, db):
    from app.models import Employee, User

    m = login(MGR)
    made = new_employee(client, m, db, "mistake@example.com")
    assert client.delete(f"/api/employees/{made['id']}", headers=m).status_code == 200
    assert db.scalar(select(Employee.id).where(Employee.id == made["id"])) is None
    assert db.scalar(select(User.id).where(User.email == "mistake@example.com")) is None
    assert db.scalars(select(AuditLog).where(AuditLog.action == "employee.delete")).one().before["email"] == "mistake@example.com"


def test_an_employee_with_history_is_refused_and_should_be_deactivated(client, login, db):
    m = login(MGR)
    made = new_employee(client, m, db, "worked@example.com")
    token = client.post("/api/auth/login", json={"email": "worked@example.com", "password": "Temp-Pass-4242"}).json()["access_token"]
    assert token
    r = client.delete(f"/api/employees/{made['id']}", headers=m)
    assert r.status_code == 409 and "deactivate them instead" in r.json()["detail"]


def test_roster_entries_and_alerts_alone_do_not_stop_a_mistaken_employee_being_deleted(client, login, db):
    from app.models import Notification, ShiftAssignment, User

    m = login(MGR)
    made = new_employee(client, m, db, "rostered@example.com")
    shift = client.get("/api/roster/shifts", headers=m).json()[0]["id"]
    assert client.post("/api/roster/assignments", headers=m, json={"employee_id": made["id"], "shift_id": shift, "location_id": made["location_ids"][0],
                                                                  "weekdays": [1, 2], "valid_from": "2030-01-01"}).status_code == 201
    account = db.scalar(select(User.id).where(User.email == "rostered@example.com"))
    db.add(Notification(user_id=account, kind="reminder", title="Welcome", dedupe_key="welcome:1"))
    db.commit()
    assert client.delete(f"/api/employees/{made['id']}", headers=m).status_code == 200
    assert db.scalar(select(ShiftAssignment.id).where(ShiftAssignment.employee_id == made["id"])) is None
    assert db.scalar(select(Notification.id).where(Notification.user_id == account)) is None


def test_an_employee_with_attendance_is_still_refused_even_if_rostered(client, login, db):
    from app.models import AttendanceRecord

    m = login(MGR)
    made = new_employee(client, m, db, "attended@example.com")
    loc = made["location_ids"][0]
    shift = client.get("/api/roster/shifts", headers=m).json()[0]["id"]
    assert client.post("/api/roster/assignments", headers=m, json={"employee_id": made["id"], "shift_id": shift, "location_id": loc,
                                                                  "weekdays": [1], "valid_from": "2030-01-01"}).status_code == 201
    db.add(AttendanceRecord(employee_id=made["id"], location_id=loc, local_date=date(2026, 3, 2), check_in_at=datetime(2026, 3, 2, 2, 5)))
    db.commit()
    r = client.delete(f"/api/employees/{made['id']}", headers=m)
    assert r.status_code == 409 and "attendance records" in r.json()["detail"]


def test_an_employee_who_others_report_to_is_refused(client, login, db):
    m = login(MGR)
    boss = new_employee(client, m, db, "boss@example.com")
    report = new_employee(client, m, db, "report@example.com")
    assert client.put(f"/api/employees/{report['id']}", json={"supervisor_id": boss["id"]}, headers=m).status_code == 200
    r = client.delete(f"/api/employees/{boss['id']}", headers=m)
    assert r.status_code == 409 and "people who report to them" in r.json()["detail"]


def test_nobody_deletes_their_own_account_and_only_managers_delete(client, login, db):
    m = login(MGR)
    me = client.get("/api/auth/me", headers=m).json()["employee"]["id"]
    assert client.delete(f"/api/employees/{me}", headers=m).status_code == 400
    other = new_employee(client, m, db, "spare@example.com")
    assert client.delete(f"/api/employees/{other['id']}", headers=login(SUP)).status_code == 403
    assert client.delete("/api/employees/99999", headers=m).status_code == 404


def test_a_checklist_nothing_was_recorded_against_is_deleted_with_its_tasks(client, login, db):
    m = login(MGR)
    body = {"name": "Spare checklist", "category": "General", "location_id": loc_id(db, "MK"), "frequency": "daily"}
    made = client.post("/api/checklists/templates", json=body, headers=m).json()
    task = client.post(f"/api/checklists/templates/{made['id']}/tasks", json={"description": "Wipe the pass"}, headers=m).json()
    assert client.post(f"/api/checklists/tasks/{task['id']}/remove", headers=login(SUP)).status_code == 403
    assert client.delete(f"/api/checklists/templates/{made['id']}", headers=login(STEWARD)).status_code == 403
    assert client.delete(f"/api/checklists/templates/{made['id']}", headers=m).json() == {"deleted": made["id"]}
    assert all(t["id"] != made["id"] for t in client.get("/api/checklists/templates", headers=m).json())
    assert client.delete(f"/api/checklists/templates/{made['id']}", headers=m).status_code == 404


def test_a_checklist_the_scheduler_generated_but_nobody_worked_on_can_still_be_deleted(client, login, db):
    m = login(MGR)
    body = {"name": "Mistake checklist", "category": "General", "location_id": loc_id(db, "MK"), "frequency": "daily"}
    made = client.post("/api/checklists/templates", json=body, headers=m).json()
    client.post(f"/api/checklists/templates/{made['id']}/tasks", json={"description": "Check the fridge"}, headers=m)
    assert client.post("/api/checklists/generate", json={"location_id": loc_id(db, "MK")}, headers=m).json()["created"] > 0
    assert client.delete(f"/api/checklists/templates/{made['id']}", headers=m).json() == {"deleted": made["id"]}


def test_a_checklist_or_task_with_records_is_refused(client, login, db):
    from app.models import ChecklistInstance

    m = login(MGR)
    body = {"name": "Used checklist", "category": "General", "location_id": loc_id(db, "MK"), "frequency": "daily"}
    made = client.post("/api/checklists/templates", json=body, headers=m).json()
    task = client.post(f"/api/checklists/templates/{made['id']}/tasks", json={"description": "Check the fridge"}, headers=m).json()
    assert client.post("/api/checklists/generate", json={"location_id": loc_id(db, "MK")}, headers=m).status_code in (200, 201)
    db.query(ChecklistInstance).filter(ChecklistInstance.task_id == task["id"]).update({"status": "completed"})
    db.commit()
    r = client.delete(f"/api/checklists/templates/{made['id']}", headers=m)
    assert r.status_code == 409 and "make it inactive instead" in r.json()["detail"]
    r = client.post(f"/api/checklists/tasks/{task['id']}/remove", headers=m)
    assert r.status_code == 409 and "records of work done" in r.json()["detail"]

def test_a_checklist_ignored_for_days_is_a_record_and_cannot_be_deleted(client, login, db):
    from datetime import date

    from app.models import ChecklistInstance

    m = login(MGR)
    body = {"name": "Ignored checklist", "category": "General", "location_id": loc_id(db, "MK"), "frequency": "daily"}
    made = client.post("/api/checklists/templates", json=body, headers=m).json()
    task = client.post(f"/api/checklists/templates/{made['id']}/tasks", json={"description": "Check the fridge"}, headers=m).json()
    client.post("/api/checklists/generate", json={"location_id": loc_id(db, "MK")}, headers=m)
    db.query(ChecklistInstance).filter(ChecklistInstance.task_id == task["id"]).update({"local_date": date(2026, 2, 20), "status": "overdue"})
    db.commit()
    assert client.delete(f"/api/checklists/templates/{made['id']}", headers=m).status_code == 409
