from pathlib import Path

from sqlalchemy import select

from app.config import settings
from app.models import AuditLog, Notification, Role, TrainingAssignment, User

from .helpers import MGR, STEWARD, SUP, loc_id
from .test_absences import emp_id

URL = "/api/training"


def stored() -> set[str]:
    folder = Path(settings.upload_dir) / "training"
    return {p.name for p in folder.iterdir()} if folder.is_dir() else set()


def mp4(size: int = 4096) -> bytes:
    return b"\x00\x00\x00\x18ftypmp42" + b"\x00" * (size - 12)


def add_lesson(client, h, course_id, title, kind, **extra):
    r = client.post(f"{URL}/courses/{course_id}/lessons", json={"title": title, "kind": kind, **extra}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def upload(client, h, lesson_id, name, data):
    return client.post(f"{URL}/lessons/{lesson_id}/media", files={"file": (name, data, "application/octet-stream")}, headers=h)


def full_course(client, h, title="Food Safety Basics"):
    """A published course of a text lesson, a video and a two-question quiz (right answers: B and x)."""
    course = client.post(f"{URL}/courses", json={"title": title, "description": "Start here", "pass_mark": 50}, headers=h).json()
    text = add_lesson(client, h, course["id"], "Welcome", "text", body="Wash your hands.")
    video = add_lesson(client, h, course["id"], "Cold storage", "video")
    assert upload(client, h, video["id"], "cold.mp4", mp4()).status_code == 201
    quiz = add_lesson(client, h, course["id"], "Check yourself", "quiz")
    questions = [{"text": "Which is right?", "options": ["A", "B"], "correct": 1}, {"text": "And this?", "options": ["x", "y", "z"], "correct": 0}]
    assert client.put(f"{URL}/lessons/{quiz['id']}/questions", json={"questions": questions}, headers=h).status_code == 200
    assert client.put(f"{URL}/courses/{course['id']}", json={"status": "published"}, headers=h).status_code == 200
    return {"id": course["id"], "text": text["id"], "video": video["id"], "quiz": quiz["id"]}


def assign_to_steward(client, h, course_id, **extra):
    return client.post(f"{URL}/courses/{course_id}/assign", json={"employee_ids": [emp_id(client, h, "E004")], **extra}, headers=h)


def my_assignment(client, steward, course_id):
    items = client.get(f"{URL}/my", headers=steward).json()["items"]
    return next(i for i in items if i["course_id"] == course_id)


def test_a_course_needs_content_before_it_can_be_published_or_assigned(client, login):
    h = login(MGR)
    course = client.post(f"{URL}/courses", json={"title": "Empty course"}, headers=h).json()
    r = client.put(f"{URL}/courses/{course['id']}", json={"status": "published"}, headers=h)
    assert r.status_code == 400 and "at least one lesson" in r.json()["detail"]
    video = add_lesson(client, h, course["id"], "No file yet", "video")
    r = client.put(f"{URL}/courses/{course['id']}", json={"status": "published"}, headers=h)
    assert r.status_code == 400 and "needs a file" in r.json()["detail"]
    assert client.post(f"{URL}/courses/{course['id']}/assign", json={"employee_ids": [1]}, headers=h).status_code == 400
    upload(client, h, video["id"], "ok.mp4", mp4())
    assert client.put(f"{URL}/courses/{course['id']}", json={"status": "published"}, headers=h).status_code == 200
    detail = client.get(f"{URL}/courses/{course['id']}", headers=h).json()
    assert detail["problems"] == [] and detail["lesson_list"][0]["media"]["original"] == "ok.mp4"


def test_uploads_are_checked_by_kind_by_content_and_by_size(client, login, monkeypatch):
    h = login(MGR)
    before = stored()
    course = client.post(f"{URL}/courses", json={"title": "Uploads"}, headers=h).json()
    video = add_lesson(client, h, course["id"], "Video", "video")
    audio = add_lesson(client, h, course["id"], "Audio", "audio")
    document = add_lesson(client, h, course["id"], "Handbook", "document")
    text = add_lesson(client, h, course["id"], "Notes", "text")
    assert upload(client, h, text["id"], "x.mp4", mp4()).status_code == 400                          # a text lesson takes no file
    assert upload(client, h, video["id"], "notes.pdf", b"%PDF-1.4 hello").status_code == 415         # wrong kind of file for a video
    assert upload(client, h, video["id"], "fake.mp4", b"this is just text, not a video").status_code == 415   # name says video, content does not
    assert upload(client, h, video["id"], "empty.mp4", b"").status_code in (400, 415)
    assert upload(client, h, audio["id"], "talk.mp3", b"ID3\x03\x00" + b"\x00" * 200).status_code == 201
    assert upload(client, h, document["id"], "book.pdf", b"%PDF-1.4\n" + b"x" * 100).status_code == 201
    assert upload(client, h, document["id"], "sheet.xlsx", b"PK\x03\x04" + b"x" * 100).status_code == 201   # replaces the pdf
    new = stored() - before
    assert len(new) == 2 and not any(name.endswith(".pdf") for name in new)                          # the replaced file is gone, nothing half-written is left
    monkeypatch.setattr(settings, "training_max_mb", 0)
    assert upload(client, h, video["id"], "big.mp4", mp4()).status_code == 413
    assert len(stored() - before) == 2
    removed = client.delete(f"{URL}/lessons/{audio['id']}/media", headers=h).json()
    assert removed["media"] is None and len(stored() - before) == 1


def test_a_person_works_through_a_course_to_a_certificate(client, login, db):
    mgr, steward = login(MGR), login(STEWARD)
    made = full_course(client, mgr)
    assert client.get(f"{URL}/my", headers=steward).json()["items"] == []                              # not assigned yet
    r = assign_to_steward(client, mgr, made["id"], due_on="2026-03-20")
    assert r.json() == {"assigned": 1, "already_had_it": 0, "without_login": 0}
    user_id = db.scalar(select(User.id).where(User.email == STEWARD))
    assert db.scalar(select(Notification.id).where(Notification.user_id == user_id, Notification.kind == "training_assigned")) is not None

    mine = my_assignment(client, steward, made["id"])
    assert (mine["status"], mine["percent"], mine["lessons"], mine["due_on"], mine["overdue"]) == ("not_started", 0, 3, "2026-03-20", False)
    aid = mine["assignment_id"]
    outline = client.get(f"{URL}/my/{aid}", headers=steward).json()["lesson_list"]
    assert [lesson["kind"] for lesson in outline] == ["text", "video", "quiz"] and outline[2]["questions"] == 2

    assert client.post(f"{URL}/my/{aid}/lessons/{made['video']}/position", json={"position_seconds": 42}, headers=steward).status_code == 200
    assert client.get(f"{URL}/my/{aid}", headers=steward).json()["lesson_list"][1]["position_seconds"] == 42      # resumes where it was left
    assert my_assignment(client, steward, made["id"])["status"] == "in_progress"

    done = client.post(f"{URL}/my/{aid}/lessons/{made['text']}/complete", headers=steward).json()
    assert (done["done"], done["percent"], done["course_completed"]) == (1, 33, False)
    assert client.post(f"{URL}/my/{aid}/lessons/{made['quiz']}/complete", headers=steward).status_code == 400   # a quiz is passed, not ticked
    client.post(f"{URL}/my/{aid}/lessons/{made['video']}/complete", headers=steward)

    asked = client.get(f"{URL}/my/{aid}/lessons/{made['quiz']}/quiz", headers=steward).json()
    assert asked["pass_mark"] == 50 and [sorted(q) for q in asked["questions"]] == [["id", "options", "text"]] * 2   # the right answers are not sent
    assert client.post(f"{URL}/my/{aid}/lessons/{made['quiz']}/quiz", json={"answers": [1]}, headers=steward).status_code == 400
    failed = client.post(f"{URL}/my/{aid}/lessons/{made['quiz']}/quiz", json={"answers": [0, 1]}, headers=steward).json()
    assert (failed["score"], failed["passed"], failed["results"], failed["course_completed"]) == (0, False, [False, False], False)
    assert client.get(f"{URL}/my/{aid}/certificate", headers=steward).status_code == 404            # nothing to download before finishing
    passed = client.post(f"{URL}/my/{aid}/lessons/{made['quiz']}/quiz", json={"answers": [1, 0]}, headers=steward).json()
    assert (passed["score"], passed["passed"], passed["course_completed"], passed["status"], passed["percent"]) == (100, True, True, "completed", 100)
    assert passed["certificate"] is True

    pdf = client.get(f"{URL}/my/{aid}/certificate", headers=steward)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF") and pdf.headers["content-type"] == "application/pdf"
    assert "TRN-2026-" in pdf.headers["content-disposition"]
    assert db.scalar(select(Notification.id).where(Notification.user_id == user_id, Notification.kind == "training_done")) is not None
    assert my_assignment(client, steward, made["id"])["status"] == "completed"


def test_playback_links_are_signed_expire_and_allow_seeking(client, login, clock):
    mgr, steward = login(MGR), login(STEWARD)
    made = full_course(client, mgr)
    assign_to_steward(client, mgr, made["id"])
    aid = my_assignment(client, steward, made["id"])["assignment_id"]
    link = client.get(f"{URL}/my/{aid}/lessons/{made['video']}/media-url", headers=steward).json()
    assert link["type"] == "video/mp4" and link["inline"] is True and link["original"] == "cold.mp4"
    whole = client.get(link["url"])                                             # no sign-in header, as a video player sends
    assert whole.status_code == 200 and len(whole.content) == 4096 and whole.headers["content-type"] == "video/mp4"
    part = client.get(link["url"], headers={"Range": "bytes=0-9"})
    assert part.status_code == 206 and len(part.content) == 10 and part.headers["content-range"].startswith("bytes 0-9/")
    assert client.get(link["url"][:-3] + "abc").status_code == 404           # a changed signature
    assert client.get("/api/training/media/garbage").status_code == 404
    assert client.get(f"{URL}/my/{aid}/lessons/{made['text']}/media-url", headers=steward).status_code == 404   # a text lesson has no file
    clock.advance(hours=7)
    assert client.get(link["url"]).status_code == 404                           # the link stops working after a few hours


def test_people_see_only_their_own_published_training_and_only_managers_manage(client, login, db):
    mgr, steward, sup = login(MGR), login(STEWARD), login(SUP)
    made = full_course(client, mgr)
    assign_to_steward(client, mgr, made["id"])
    aid = my_assignment(client, steward, made["id"])["assignment_id"]
    assert client.get(f"{URL}/my/{aid}", headers=sup).status_code in (403, 404)       # someone else's assignment
    for method, path in [("get", "/courses"), ("post", "/courses"), ("get", "/progress"), ("get", "/progress.csv")]:
        assert getattr(client, method)(URL + path, headers=steward, **({"json": {"title": "Nope"}} if method == "post" else {})).status_code == 403
    assert client.put(f"{URL}/courses/{made['id']}", json={"title": "Changed"}, headers=steward).status_code == 403
    assert client.post(f"{URL}/courses/{made['id']}/assign", json={"employee_ids": [1]}, headers=steward).status_code == 403
    client.put(f"{URL}/courses/{made['id']}", json={"status": "draft"}, headers=mgr)           # unpublishing hides it
    assert client.get(f"{URL}/my", headers=steward).json()["items"] == []
    assert client.get(f"{URL}/my/{aid}", headers=steward).status_code == 404
    client.put(f"{URL}/courses/{made['id']}", json={"status": "published"}, headers=mgr)
    assert client.get(f"{URL}/my/{aid}", headers=steward).status_code == 200
    assert db.scalar(select(AuditLog.id).where(AuditLog.action == "training.assign")) is not None


def test_assigning_by_role_or_location_skips_people_who_have_it_or_cannot_sign_in(client, login, db):
    mgr = login(MGR)
    made = full_course(client, mgr)
    steward_role = db.scalar(select(Role.id).where(Role.name == "steward"))
    first = client.post(f"{URL}/courses/{made['id']}/assign", json={"role_ids": [steward_role], "location_ids": [loc_id(db, "MK")]}, headers=mgr).json()
    assert first["assigned"] >= 2 and first["already_had_it"] == 0
    again = client.post(f"{URL}/courses/{made['id']}/assign", json={"role_ids": [steward_role]}, headers=mgr).json()
    assert again["assigned"] == 0 and again["already_had_it"] >= 1                        # nobody is assigned twice
    assert client.post(f"{URL}/courses/{made['id']}/assign", json={}, headers=mgr).status_code == 400
    assert client.post(f"{URL}/courses/{made['id']}/assign", json={"role_ids": [steward_role], "due_on": "2020-01-01"}, headers=mgr).status_code == 400


def test_managers_track_progress_and_export_it(client, login):
    mgr, steward = login(MGR), login(STEWARD)
    made = full_course(client, mgr)
    other = full_course(client, mgr, "Fire Safety")
    assign_to_steward(client, mgr, made["id"], due_on="2026-03-05")
    assign_to_steward(client, mgr, other["id"])
    aid = my_assignment(client, steward, made["id"])["assignment_id"]
    client.post(f"{URL}/my/{aid}/lessons/{made['text']}/complete", headers=steward)
    one = client.get(f"{URL}/progress?course_id={made['id']}", headers=mgr).json()
    row = one["items"][0]
    assert (row["employee"], row["status"], row["done"], row["lessons"], row["percent"]) == ("Sid Steward", "in_progress", 1, 3, 33)
    assert row["last_activity"] and row["locations"] and one["summary"] == {"assigned": 1, "completed": 0, "in_progress": 1, "not_started": 0, "overdue": 0}
    assert {r["course"] for r in client.get(f"{URL}/progress", headers=mgr).json()["items"]} == {"Food Safety Basics", "Fire Safety"}
    listing = {c["title"]: c for c in client.get(f"{URL}/courses", headers=mgr).json()["items"]}
    assert (listing["Food Safety Basics"]["lessons"], listing["Food Safety Basics"]["assigned"], listing["Food Safety Basics"]["completed"]) == (3, 1, 0)
    csv_file = client.get(f"{URL}/progress.csv?course_id={made['id']}", headers=mgr)
    assert csv_file.status_code == 200 and csv_file.headers["content-type"].startswith("text/csv")
    lines = csv_file.text.lstrip("﻿").splitlines()
    assert lines[0].startswith("Course,Employee") and "Sid Steward" in lines[1] and "in progress" in lines[1] and len(lines) == 2


def test_unassigning_deleting_and_reordering_follow_the_rules(client, login, db):
    mgr, steward = login(MGR), login(STEWARD)
    before = stored()
    made = full_course(client, mgr)
    assign_to_steward(client, mgr, made["id"])
    aid = my_assignment(client, steward, made["id"])["assignment_id"]
    assert client.delete(f"{URL}/courses/{made['id']}", headers=mgr).status_code == 409          # people are taking it
    order = [made["quiz"], made["text"], made["video"]]
    assert client.post(f"{URL}/courses/{made['id']}/lessons/reorder", json={"lesson_ids": order[:2]}, headers=mgr).status_code == 400
    assert client.post(f"{URL}/courses/{made['id']}/lessons/reorder", json={"lesson_ids": order}, headers=mgr).status_code == 200
    assert [lesson["id"] for lesson in client.get(f"{URL}/courses/{made['id']}", headers=mgr).json()["lesson_list"]] == order
    client.post(f"{URL}/my/{aid}/lessons/{made['text']}/complete", headers=steward)
    assert client.delete(f"{URL}/assignments/{aid}", headers=mgr).json() == {"deleted": aid}         # taken back before it was finished
    assert db.scalar(select(TrainingAssignment.id).where(TrainingAssignment.id == aid)) is None
    assert client.delete(f"{URL}/lessons/{made['video']}", headers=mgr).status_code == 200
    assert stored() == before                                                                            # its file went with it
    assert client.delete(f"{URL}/courses/{made['id']}", headers=mgr).json() == {"deleted": made["id"]}
    assert client.get(f"{URL}/courses/{made['id']}", headers=mgr).status_code == 404


def test_finished_training_stays_on_record(client, login):
    mgr, steward = login(MGR), login(STEWARD)
    course = client.post(f"{URL}/courses", json={"title": "Short one"}, headers=mgr).json()
    lesson = add_lesson(client, mgr, course["id"], "Read this", "text", body="Hello there")
    client.put(f"{URL}/courses/{course['id']}", json={"status": "published"}, headers=mgr)
    assign_to_steward(client, mgr, course["id"])
    aid = my_assignment(client, steward, course["id"])["assignment_id"]
    assert client.post(f"{URL}/my/{aid}/lessons/{lesson['id']}/complete", headers=steward).json()["course_completed"] is True
    assert client.delete(f"{URL}/assignments/{aid}", headers=mgr).status_code == 409
    certificate = client.get(f"{URL}/assignments/{aid}/certificate", headers=mgr)
    assert certificate.status_code == 200 and certificate.content.startswith(b"%PDF")
