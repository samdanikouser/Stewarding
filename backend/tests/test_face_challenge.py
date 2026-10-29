import base64
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select

from app.config import settings
from app.models import AttendanceRecord, AuditLog

from .helpers import MGR, STEWARD, STEWARD_RB, SUP, SUP_RB, loc_id
from .test_attendance import check_in
from .test_face_verification import enroll, face, turn_on

SNAP = base64.b64encode(b"\xff\xd8\xff\xe0 pretend this is a small photo").decode()
OUT = "/api/attendance/check-out"


def ready(client, login):
    assert turn_on(client, login, live=1).status_code == 200
    assert enroll(client, login, face()).status_code == 200


def challenge(client, h, action="in"):
    made = client.post("/api/attendance/face-challenge", json={"action": action}, headers=h)
    assert made.status_code == 201
    return made.json()


def evidence(c, **over):
    return {"challenge": c["token"], "liveness": c["steps"], "snapshot": SNAP, "face": face(0.001), **over}


def test_no_challenge_is_needed_while_face_checks_or_live_checks_are_off(client, login, db, clock):
    h = login(STEWARD)
    assert challenge(client, h) == {"required": False}
    turn_on(client, login, live=0)
    assert challenge(client, h) == {"required": False}


def test_every_challenge_asks_for_both_directions_and_they_differ_between_challenges(client, login, db, clock):
    ready(client, login)
    h = login(STEWARD)
    sequences = {tuple(challenge(client, h)["steps"]) for _ in range(9)}
    assert all(set(seq) == {"turn_left", "turn_right"} for seq in sequences) and len(sequences) > 1


def test_a_live_check_in_needs_the_challenge_the_right_turns_and_a_snapshot(client, login, db, clock):
    ready(client, login)
    h = login(STEWARD)
    assert check_in(client, h, db, face=face(0.001)).status_code == 400                      # no snapshot, no challenge
    c = challenge(client, h)
    assert c["required"] and len(c["steps"]) == 3 and set(c["steps"]) <= {"turn_left", "turn_right"}
    assert check_in(client, h, db, **evidence(c)).status_code == 400                          # at once: too quick to be live
    assert check_in(client, h, db, **evidence(c)).status_code == 400                          # and that challenge is spent
    c = challenge(client, h)
    clock.advance(seconds=6)
    wrong = ["turn_left" if s == "turn_right" else "turn_right" for s in c["steps"]]
    assert check_in(client, h, db, **evidence(c, liveness=wrong)).status_code == 400          # other turns than asked
    c = challenge(client, h)
    clock.advance(seconds=6)
    assert check_in(client, h, db, **evidence(c, face=face(0.5))).status_code == 403          # a different face still fails
    c = challenge(client, h)
    clock.advance(seconds=6)
    done = check_in(client, h, db, **evidence(c))
    assert done.status_code == 201 and done.json()["snapshot_in"] is True and done.json()["snapshot_out"] is False
    saved = db.scalar(select(AttendanceRecord).order_by(AttendanceRecord.id.desc()))
    assert (Path(settings.upload_dir) / "faces" / saved.check_in_snapshot).read_bytes().startswith(b"\xff\xd8\xff")
    assert check_in(client, h, db, **evidence(c)).status_code in (400, 409)                    # never twice


def test_a_challenge_expires_and_belongs_to_one_person(client, login, db, clock):
    ready(client, login)
    h = login(STEWARD)
    c = challenge(client, h)
    clock.advance(seconds=301)
    assert check_in(client, h, db, **evidence(c)).status_code == 400
    c = challenge(client, login(STEWARD_RB))
    clock.advance(seconds=6)
    assert check_in(client, h, db, **evidence(c)).status_code == 400                          # somebody else's challenge


def test_a_bad_snapshot_is_refused_before_a_challenge_is_spent(client, login, db, clock):
    ready(client, login)
    h = login(STEWARD)
    c = challenge(client, h)
    clock.advance(seconds=6)
    assert check_in(client, h, db, **evidence(c, snapshot="not base64 !!")).status_code == 400
    assert check_in(client, h, db, **evidence(c, snapshot=base64.b64encode(b"not a jpeg").decode())).status_code == 400
    assert check_in(client, h, db, **evidence(c)).status_code == 201                          # the challenge was still unspent


def test_a_check_out_with_open_tasks_keeps_the_challenge_for_the_reason(client, login, db, clock):
    ready(client, login)
    h = login(STEWARD)
    c = challenge(client, h)
    clock.advance(seconds=6)
    assert check_in(client, h, db, **evidence(c)).status_code == 201
    assert client.post("/api/checklists/generate", json={"location_id": loc_id(db, "MK")}, headers=login(MGR)).status_code == 200
    c = challenge(client, h, "out")
    clock.advance(seconds=6)
    first = client.post(OUT, json=evidence(c), headers=h)
    assert first.status_code == 409                                                           # open tasks, nothing spent yet
    clock.advance(seconds=30)
    again = client.post(OUT, json={**evidence(c), "exception_reason": "Testing the live check"}, headers=h)
    assert again.status_code == 200 and again.json()["snapshot_out"] is True
    assert client.post(OUT, json=evidence(c), headers=h).status_code in (400, 409)


def test_only_people_who_may_view_attendance_there_can_open_a_snapshot_and_it_is_audited(client, login, db, clock):
    ready(client, login)
    h = login(STEWARD)
    c = challenge(client, h)
    clock.advance(seconds=6)
    record_id = check_in(client, h, db, **evidence(c)).json()["id"]
    url = f"/api/attendance/{record_id}/snapshot/in"
    shown = client.get(url, headers=login(SUP))
    assert shown.status_code == 200 and shown.headers["content-type"] == "image/jpeg" and "no-store" in shown.headers["cache-control"]
    assert client.get(url, headers=login(MGR)).status_code == 200
    assert client.get(url, headers=h).status_code == 403                                      # the steward cannot view attendance
    assert client.get(url, headers=login(SUP_RB)).status_code == 403                          # another site's supervisor
    assert client.get(f"/api/attendance/{record_id}/snapshot/out", headers=login(SUP)).status_code == 404
    assert len(db.scalars(select(AuditLog).where(AuditLog.action == "attendance.snapshot_view")).all()) == 2


def test_old_snapshots_are_deleted_after_the_retention_period(client, login, db, clock):
    from app.services.face_snapshots import purge_face_snapshots

    ready(client, login)
    h = login(STEWARD)
    c = challenge(client, h)
    clock.advance(seconds=6)
    check_in(client, h, db, **evidence(c))
    record = db.scalar(select(AttendanceRecord).order_by(AttendanceRecord.id.desc()))
    path = Path(settings.upload_dir) / "faces" / record.check_in_snapshot
    assert purge_face_snapshots(db, clock.now + timedelta(days=89)) == 0 and path.is_file()
    assert purge_face_snapshots(db, clock.now + timedelta(days=91)) == 1
    db.commit()
    db.refresh(record)
    assert not path.exists() and record.check_in_snapshot is None
    client.put("/api/settings", json={"values": {"attendance.snapshot_days": 0}}, headers=login(MGR))
    assert purge_face_snapshots(db, clock.now + timedelta(days=4000)) == 0
