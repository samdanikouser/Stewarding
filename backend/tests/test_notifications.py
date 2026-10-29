from sqlalchemy import select

from app.models import Notification, User
from app.services.alerts import run_alerts
from app.services.notify import notify

from .helpers import MGR, STEWARD, SUP, SUP_RB, loc_id


def give(db, email, **kw):
    user = db.scalar(select(User).where(User.email == email))
    notify(db, [user.id], kw.pop("kind", "test"), kw.pop("title", "A notification"), key=kw.pop("key", "k1"), **kw)
    db.commit()
    return db.scalar(select(Notification).where(Notification.user_id == user.id).order_by(Notification.id.desc()))


def test_users_only_see_their_own_notifications(client, login, db):
    mine = give(db, STEWARD, key="a")
    give(db, SUP, key="b")
    items = client.get("/api/notifications", headers=login(STEWARD)).json()["items"]
    assert [i["id"] for i in items] == [mine.id]
    other = give(db, SUP, key="c")
    assert client.post(f"/api/notifications/{other.id}/read", headers=login(STEWARD)).status_code == 404
    assert client.post(f"/api/notifications/{other.id}/acknowledge", headers=login(STEWARD)).status_code == 404
    assert client.get("/api/notifications").status_code == 401


def test_unread_counts_read_and_read_all(client, login, db):
    first = give(db, STEWARD, key="a")
    give(db, STEWARD, key="b")
    h = login(STEWARD)
    assert client.get("/api/notifications/unread-count", headers=h).json()["unread"] == 2
    assert client.post(f"/api/notifications/{first.id}/read", headers=h).json()["read_at"]
    assert client.get("/api/notifications?unread=true", headers=h).json()["total"] == 1
    client.post("/api/notifications/read-all", headers=h)
    assert client.get("/api/notifications/unread-count", headers=h).json()["unread"] == 0


def test_notifications_carry_priority_location_link_and_due_time(client, login, db):
    give(db, STEWARD, key="a", priority="high", location_id=loc_id(db, "MK"), link="/checklists")
    item = client.get("/api/notifications", headers=login(STEWARD)).json()["items"][0]
    assert item["priority"] == "high" and item["location_id"] == loc_id(db, "MK") and item["link"] == "/checklists"
    assert client.get("/api/notifications?priority=critical", headers=login(STEWARD)).json()["total"] == 0


def test_critical_alert_stays_open_after_reading_until_acknowledged(client, login, db):
    alert = give(db, SUP, key="crit", priority="critical", requires_ack=True)
    h = login(SUP)
    assert client.post(f"/api/notifications/{alert.id}/read", headers=h).json()["action_needed"] is True
    assert client.get("/api/notifications/unread-count", headers=h).json()["action_needed"] == 1
    acked = client.post(f"/api/notifications/{alert.id}/acknowledge", headers=h).json()
    assert acked["acknowledged_at"] and acked["action_needed"] is False
    assert client.get("/api/notifications/unread-count", headers=h).json()["action_needed"] == 0


def test_open_critical_alerts_are_listed_first(client, login, db):
    give(db, SUP, key="crit", priority="critical", requires_ack=True, title="Critical")
    give(db, SUP, key="later", title="Newer ordinary")
    items = client.get("/api/notifications", headers=login(SUP)).json()["items"]
    assert items[0]["title"] == "Critical"


def test_failed_check_alert_closes_when_the_retest_passes(client, login, db, clock):
    h = login(STEWARD)
    eq = next(e for e in client.get("/api/monitoring/equipment", headers=h).json() if e["code"] == "DW-MK-1")
    sched = next(s for s in eq["schedules"] if s["stage"] == "wash")
    failed = client.post("/api/monitoring/readings", headers=h, json={
        "equipment_id": eq["id"], "schedule_id": sched["id"], "value": 30, "corrective_action": "Cleaned the heater"}).json()
    sup = login(SUP)
    before = client.get("/api/notifications", headers=sup).json()["items"]
    assert before[0]["kind"] == "monitoring_failed" and before[0]["action_needed"] is True
    clock.advance(minutes=20)
    client.post("/api/monitoring/readings", headers=h, json={
        "equipment_id": eq["id"], "schedule_id": sched["id"], "value": 60, "retest_of_id": failed["id"]})
    after = client.get("/api/notifications", headers=sup).json()["items"]
    assert next(i for i in after if i["kind"] == "monitoring_failed")["action_needed"] is False


def test_notification_events_are_deduplicated_per_recipient(client, login, db):
    user = db.scalar(select(User).where(User.email == STEWARD))
    assert notify(db, [user.id, user.id], "x", "Once", key="same") == 1
    assert notify(db, [user.id], "x", "Once", key="same") == 0
    db.commit()
    assert len(db.scalars(select(Notification).where(Notification.dedupe_key == "same")).all()) == 1


def test_pending_summary_is_grouped_scoped_and_permissioned(client, login, db, clock):
    client.put("/api/settings", json={"values": {"checklist.grace_minutes": 0}}, headers=login(MGR))
    client.post("/api/checklists/generate", json={"location_id": loc_id(db, "MK")}, headers=login(MGR))
    clock.set(2026, 3, 2, 9, 40)  # 13:40 Dubai: daily tasks are 10 minutes overdue, temperature checks overdue
    assert client.get("/api/notifications/pending-summary", headers=login(STEWARD)).status_code == 403
    sup = client.get("/api/notifications/pending-summary", headers=login(SUP)).json()
    assert sup["total"] > 0 and set(sup["by_location"]) <= {"Main Kitchen", "Banquet Hall"}
    assert {"critical", "high", "normal"} == set(sup["by_urgency"])
    task = next(i for i in sup["items"] if i["category"] == "overdue_task")
    assert task["overdue_minutes"] == 10 and task["responsible"].startswith("Unassigned") and task["location"] == "Main Kitchen"
    assert sup["items"][0]["urgency"] == "critical"
    rb = client.get("/api/notifications/pending-summary", headers=login(SUP_RB)).json()
    assert set(rb["by_location"]) <= {"Rooftop Bar"}
    manager = client.get("/api/notifications/pending-summary", headers=login(MGR)).json()
    assert manager["total"] >= sup["total"] and "Rooftop Bar" in manager["by_location"]
    forbidden = client.get(f"/api/notifications/pending-summary?location_id={loc_id(db, 'MK')}", headers=login(SUP_RB))
    assert forbidden.status_code == 403


def test_future_tasks_are_not_pending(client, login, db, clock):
    client.post("/api/checklists/generate", json={"location_id": loc_id(db, "MK")}, headers=login(MGR))
    summary = client.get("/api/notifications/pending-summary", headers=login(SUP)).json()
    assert not [i for i in summary["items"] if i["category"] == "overdue_task"]


def test_pending_summary_lists_verification_breakage_and_transfers(client, login, db, clock):
    from .helpers import item_id

    client.post("/api/checklists/generate", json={"location_id": loc_id(db, "MK")}, headers=login(MGR))
    task = next(t for t in client.get("/api/checklists/instances?size=200", headers=login(STEWARD)).json()["items"]
                if "dishwasher filters" in t["description"])
    client.post(f"/api/checklists/instances/{task['id']}/complete", json={}, headers=login(STEWARD))
    client.post("/api/breakage", headers=login(STEWARD), json={
        "location_id": loc_id(db, "MK"), "item_id": item_id(db, "PL-001"), "qty": 1, "incident_type": "breakage"})
    client.post("/api/stock/transfers", headers=login(SUP), json={
        "from_location_id": loc_id(db, "MK"), "to_location_id": loc_id(db, "BQ"), "lines": [{"item_id": item_id(db, "PL-001"), "qty": 1}]})
    categories = {i["category"] for i in client.get("/api/notifications/pending-summary", headers=login(MGR)).json()["items"]}
    assert {"verification", "breakage", "transfer"} <= categories


def test_run_alerts_returns_counts(db, clock):
    totals = run_alerts(db, clock.now)
    assert set(totals) == {"checkins", "checklists", "monitoring", "summary", "checkouts", "corrective", "low_stock", "pending_time_outs", "closed", "rounds"}
