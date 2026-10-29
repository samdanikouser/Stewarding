import csv
import errno
import io
import uuid
from datetime import date
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .. import timeutil
from ..audit import audit
from ..config import settings
from ..db import get_db
from ..deps import require
from ..models import (Employee, EmployeeLocation, Location, TrainingAssignment, TrainingAttempt, TrainingCourse, TrainingLesson,
                      TrainingProgress, TrainingQuestion, User)
from ..services import slidevideo, voice
from ..services import training as engine
from ..services.notify import notify

router = APIRouter(prefix="/api/training", tags=["training"])

Kind = Literal["video", "audio", "document", "text", "link", "quiz"]


def _clean(value: str | None) -> str | None:
    return " ".join(value.split()) if value and value.strip() else None


class CourseIn(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    category: str | None = Field(default=None, max_length=60)
    pass_mark: int = Field(default=80, ge=1, le=100)
    certificate: bool = True


class CourseEdit(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    category: str | None = Field(default=None, max_length=60)
    pass_mark: int | None = Field(default=None, ge=1, le=100)
    certificate: bool | None = None
    status: Literal["draft", "published"] | None = None


def _web_address(value: str | None) -> str | None:
    if value and not value.strip().lower().startswith(("http://", "https://")):
        raise ValueError("A link must start with http:// or https://")
    return value.strip() if value else None


class LessonIn(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    kind: Kind
    body: str | None = Field(default=None, max_length=20000)
    external_url: str | None = Field(default=None, max_length=500)
    _url = field_validator("external_url")(_web_address)


class LessonEdit(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=200)
    kind: Kind | None = None
    body: str | None = Field(default=None, max_length=20000)
    external_url: str | None = Field(default=None, max_length=500)
    _url = field_validator("external_url")(_web_address)


class QuestionIn(BaseModel):
    text: str = Field(min_length=2, max_length=500)
    options: list[str] = Field(min_length=2, max_length=6)
    correct: int = Field(ge=0)

    @field_validator("options")
    @classmethod
    def _filled(cls, options: list[str]) -> list[str]:
        cleaned = [" ".join(o.split()) for o in options]
        if any(not o or len(o) > 200 for o in cleaned):
            raise ValueError("Every answer needs some text, at most 200 characters")
        return cleaned


class QuestionsIn(BaseModel):
    questions: list[QuestionIn] = Field(max_length=100)


class ReorderIn(BaseModel):
    lesson_ids: list[int]


class AssignIn(BaseModel):
    employee_ids: list[int] = Field(default_factory=list, max_length=2000)
    role_ids: list[int] = Field(default_factory=list, max_length=100)
    location_ids: list[int] = Field(default_factory=list, max_length=100)
    due_on: date | None = None


def _course_or_404(db: Session, course_id: int) -> TrainingCourse:
    course = db.get(TrainingCourse, course_id)
    if not course:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Course not found")
    return course


def _lesson_or_404(db: Session, lesson_id: int) -> TrainingLesson:
    lesson = db.get(TrainingLesson, lesson_id)
    if not lesson:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lesson not found")
    return lesson


def _course_dict(course: TrainingCourse) -> dict:
    return {"id": course.id, "title": course.title, "description": course.description, "category": course.category,
            "status": course.status, "pass_mark": course.pass_mark, "certificate": course.certificate,
            "created_at": course.created_at.isoformat(), "updated_at": course.updated_at.isoformat()}


def _lesson_dict(lesson: TrainingLesson, questions: list[TrainingQuestion]) -> dict:
    return {"id": lesson.id, "position": lesson.position, "title": lesson.title, "kind": lesson.kind, "body": lesson.body,
            "external_url": lesson.external_url,
            "media": {"original": lesson.media_original, "type": lesson.media_type, "size": lesson.media_size} if lesson.media_name else None,
            "slides": [{"id": s["id"], "title": s["title"], "bullets": s["bullets"], "narration": s["narration"], "voice": s["voice"],
                        "seconds": s["seconds"], "image": s.get("image_original"), "audio": s.get("audio_original")} for s in lesson.slides or []],
            "video": {"status": lesson.video_status, "error": lesson.video_error},
            "questions": [{"id": q.id, "text": q.text, "options": q.options, "correct": q.correct} for q in questions]}


def _questions_of(db: Session, lesson_id: int) -> list[TrainingQuestion]:
    return list(db.scalars(select(TrainingQuestion).where(TrainingQuestion.lesson_id == lesson_id).order_by(TrainingQuestion.position, TrainingQuestion.id)))


def _forget_file(name: str | None) -> None:
    if name:
        engine.media_path(name).unlink(missing_ok=True)


def _files_of(lesson: TrainingLesson) -> set[str]:
    """Every stored file a lesson holds: its own, and the pictures and recordings of its slides."""
    return ({lesson.media_name} if lesson.media_name else set()) | slidevideo.asset_names(lesson.slides)


async def _save_upload(file: UploadFile, allowed: dict[str, str], what: str, limit_mb: int | None = None) -> tuple[str, str, int]:
    """Writes an upload to disk in pieces after checking its type, its first bytes and its size; returns the stored name, extension and size."""
    ext = Path(file.filename or "").suffix.lower()
    if ext not in allowed:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, f"{what} takes {', '.join(sorted(allowed))} files")
    limit_mb = limit_mb or settings.training_max_mb
    limit = limit_mb * 1024 * 1024
    engine.media_dir().mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}{ext}"
    path = engine.media_path(name)
    size = 0
    try:
        with path.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                if size == 0 and not engine.signature_ok(ext, chunk[:64]):
                    raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, f"This file is not a real {ext} file")
                size += len(chunk)
                if size > limit:
                    raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, f"The file is larger than {limit_mb} MB")
                out.write(chunk)
        if size == 0:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "The file is empty")
    except HTTPException:
        path.unlink(missing_ok=True)
        raise
    except OSError as exc:
        path.unlink(missing_ok=True)
        if exc.errno == errno.ENOSPC:
            raise HTTPException(status.HTTP_507_INSUFFICIENT_STORAGE, "The server's disk is full. Remove old training files or ask for more space") from None
        raise
    return name, ext, size


@router.get("/courses")
def list_courses(user: User = Depends(require("settings.manage")), db: Session = Depends(get_db)):
    courses = list(db.scalars(select(TrainingCourse).order_by(TrainingCourse.title)))
    lessons = dict(db.execute(select(TrainingLesson.course_id, func.count()).group_by(TrainingLesson.course_id)).all())
    assigned: dict[int, dict] = {}
    for course_id, completed in db.execute(select(TrainingAssignment.course_id, TrainingAssignment.completed_at)):
        slot = assigned.setdefault(course_id, {"assigned": 0, "completed": 0})
        slot["assigned"] += 1
        slot["completed"] += 1 if completed else 0
    return {"items": [{**_course_dict(c), "lessons": lessons.get(c.id, 0), **assigned.get(c.id, {"assigned": 0, "completed": 0})} for c in courses]}


@router.post("/courses", status_code=201)
def create_course(body: CourseIn, user: User = Depends(require("settings.manage")), db: Session = Depends(get_db)):
    course = TrainingCourse(title=" ".join(body.title.split()), description=_clean(body.description), category=_clean(body.category),
                            pass_mark=body.pass_mark, certificate=body.certificate, created_by=user.id)
    db.add(course)
    db.flush()
    audit(db, user, "training.course_create", "training_course", course.id, None, {"title": course.title})
    db.commit()
    return _course_dict(course)


@router.get("/courses/{course_id}")
def get_course(course_id: int, user: User = Depends(require("settings.manage")), db: Session = Depends(get_db)):
    course = _course_or_404(db, course_id)
    lessons = engine.lessons_of(db, course.id)
    return {**_course_dict(course), "problems": engine.publish_problems(db, course),
            "lesson_list": [_lesson_dict(lesson, _questions_of(db, lesson.id) if lesson.kind == "quiz" else []) for lesson in lessons]}


@router.put("/courses/{course_id}")
def update_course(course_id: int, body: CourseEdit, user: User = Depends(require("settings.manage")), db: Session = Depends(get_db)):
    course = _course_or_404(db, course_id)
    data = body.model_dump(exclude_unset=True)
    if data.get("status") == "published" and course.status != "published":
        problems = engine.publish_problems(db, course)
        if problems:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "This course cannot be published yet: " + "; ".join(problems[:3]))
    before = {k: getattr(course, k) for k in data}
    for key, value in data.items():
        if key == "title" and value:
            value = " ".join(value.split())
        elif key in ("description", "category"):
            value = _clean(value)
        setattr(course, key, value)
    course.updated_at = timeutil.utc_now()
    audit(db, user, "training.course_update", "training_course", course.id, before, data)
    db.commit()
    return _course_dict(course)


@router.delete("/courses/{course_id}")
def delete_course(course_id: int, user: User = Depends(require("settings.manage")), db: Session = Depends(get_db)):
    course = _course_or_404(db, course_id)
    taken = db.scalar(select(func.count()).select_from(TrainingAssignment).where(TrainingAssignment.course_id == course.id))
    if taken:
        raise HTTPException(status.HTTP_409_CONFLICT, f"This course is assigned to {taken} {'person' if taken == 1 else 'people'}; unpublish it instead")
    files = []
    for lesson in engine.lessons_of(db, course.id):
        db.execute(delete(TrainingQuestion).where(TrainingQuestion.lesson_id == lesson.id))
        files.extend(_files_of(lesson))
        db.delete(lesson)
    db.flush()
    audit(db, user, "training.course_delete", "training_course", course.id, {"title": course.title}, None)
    db.delete(course)
    db.commit()
    for name in files:
        _forget_file(name)
    return {"deleted": course_id}


@router.post("/courses/{course_id}/lessons", status_code=201)
def add_lesson(course_id: int, body: LessonIn, user: User = Depends(require("settings.manage")), db: Session = Depends(get_db)):
    course = _course_or_404(db, course_id)
    last = db.scalar(select(func.max(TrainingLesson.position)).where(TrainingLesson.course_id == course.id))
    lesson = TrainingLesson(course_id=course.id, position=(last + 1) if last is not None else 0, title=" ".join(body.title.split()),
                            kind=body.kind, body=body.body, external_url=body.external_url)
    db.add(lesson)
    course.updated_at = timeutil.utc_now()
    db.flush()
    audit(db, user, "training.lesson_add", "training_lesson", lesson.id, None, {"course_id": course.id, "title": lesson.title, "kind": lesson.kind})
    db.commit()
    return _lesson_dict(lesson, [])


@router.post("/courses/{course_id}/lessons/reorder")
def reorder_lessons(course_id: int, body: ReorderIn, user: User = Depends(require("settings.manage")), db: Session = Depends(get_db)):
    course = _course_or_404(db, course_id)
    lessons = {lesson.id: lesson for lesson in engine.lessons_of(db, course.id)}
    if sorted(body.lesson_ids) != sorted(lessons):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "List every lesson of the course once")
    for position, lesson_id in enumerate(body.lesson_ids):
        lessons[lesson_id].position = position
    course.updated_at = timeutil.utc_now()
    audit(db, user, "training.lessons_reorder", "training_course", course.id, None, {"order": body.lesson_ids})
    db.commit()
    return {"ok": True}


@router.put("/lessons/{lesson_id}")
def update_lesson(lesson_id: int, body: LessonEdit, user: User = Depends(require("settings.manage")), db: Session = Depends(get_db)):
    lesson = _lesson_or_404(db, lesson_id)
    data = body.model_dump(exclude_unset=True)
    new_kind = data.get("kind", lesson.kind)
    if new_kind != lesson.kind and lesson.media_name and lesson.media_type not in engine.MEDIA.get(new_kind, {}).values():
        raise HTTPException(status.HTTP_409_CONFLICT, "Remove the file before changing this lesson to a kind that cannot play it")
    before = {k: getattr(lesson, k) for k in data if k != "body"}
    for key, value in data.items():
        setattr(lesson, key, " ".join(value.split()) if key == "title" and value else value)
    _course_or_404(db, lesson.course_id).updated_at = timeutil.utc_now()
    audit(db, user, "training.lesson_update", "training_lesson", lesson.id, before, {k: v for k, v in data.items() if k != "body"})
    db.commit()
    return _lesson_dict(lesson, _questions_of(db, lesson.id) if lesson.kind == "quiz" else [])


@router.delete("/lessons/{lesson_id}")
def delete_lesson(lesson_id: int, user: User = Depends(require("settings.manage")), db: Session = Depends(get_db)):
    lesson = _lesson_or_404(db, lesson_id)
    db.execute(delete(TrainingProgress).where(TrainingProgress.lesson_id == lesson.id))
    db.execute(delete(TrainingAttempt).where(TrainingAttempt.lesson_id == lesson.id))
    db.execute(delete(TrainingQuestion).where(TrainingQuestion.lesson_id == lesson.id))
    files = _files_of(lesson)
    audit(db, user, "training.lesson_delete", "training_lesson", lesson.id, {"course_id": lesson.course_id, "title": lesson.title}, None)
    _course_or_404(db, lesson.course_id).updated_at = timeutil.utc_now()
    db.delete(lesson)
    db.commit()
    for name in files:
        _forget_file(name)
    return {"deleted": lesson_id}


@router.put("/lessons/{lesson_id}/questions")
def set_questions(lesson_id: int, body: QuestionsIn, user: User = Depends(require("settings.manage")), db: Session = Depends(get_db)):
    lesson = _lesson_or_404(db, lesson_id)
    if lesson.kind != "quiz":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only a quiz lesson has questions")
    for question in body.questions:
        if question.correct >= len(question.options):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f'Mark one of the answers to "{question.text}" as the right one')
    db.execute(delete(TrainingQuestion).where(TrainingQuestion.lesson_id == lesson.id))
    for position, question in enumerate(body.questions):
        db.add(TrainingQuestion(lesson_id=lesson.id, position=position, text=" ".join(question.text.split()), options=question.options, correct=question.correct))
    audit(db, user, "training.questions_update", "training_lesson", lesson.id, None, {"questions": len(body.questions)})
    db.commit()
    return _lesson_dict(lesson, _questions_of(db, lesson.id))


@router.post("/lessons/{lesson_id}/media", status_code=201)
async def upload_media(lesson_id: int, file: UploadFile, user: User = Depends(require("settings.manage")), db: Session = Depends(get_db)):
    """Takes a video, audio file or document for a lesson. It is written to disk in pieces, so a large video never sits in memory."""
    lesson = _lesson_or_404(db, lesson_id)
    allowed = engine.MEDIA.get(lesson.kind)
    if not allowed:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This kind of lesson takes no file")
    if lesson.video_status in ("queued", "rendering"):
        raise HTTPException(status.HTTP_409_CONFLICT, "The video is being made; wait for it to finish")
    name, ext, size = await _save_upload(file, allowed, f"A {lesson.kind} lesson")
    old = lesson.media_name
    lesson.media_name, lesson.media_original, lesson.media_type, lesson.media_size = name, (file.filename or name)[:255], allowed[ext], size
    lesson.video_status = lesson.video_error = None  # a file put here is not the one the slides made
    _course_or_404(db, lesson.course_id).updated_at = timeutil.utc_now()
    audit(db, user, "training.media_upload", "training_lesson", lesson.id, None, {"file": lesson.media_original, "bytes": size})
    db.commit()
    _forget_file(old)
    return _lesson_dict(lesson, [])


@router.delete("/lessons/{lesson_id}/media")
def remove_media(lesson_id: int, user: User = Depends(require("settings.manage")), db: Session = Depends(get_db)):
    lesson = _lesson_or_404(db, lesson_id)
    name = lesson.media_name
    lesson.media_name = lesson.media_original = lesson.media_type = lesson.media_size = None
    lesson.video_status = lesson.video_error = None
    audit(db, user, "training.media_remove", "training_lesson", lesson.id, None, None)
    db.commit()
    _forget_file(name)
    return _lesson_dict(lesson, [])


def _targets(db: Session, body: AssignIn) -> set[int]:
    ids = set(body.employee_ids)
    if body.role_ids:
        ids |= set(db.scalars(select(Employee.id).join(User, User.id == Employee.user_id).where(User.role_id.in_(body.role_ids))))
    if body.location_ids:
        ids |= set(db.scalars(select(EmployeeLocation.employee_id).where(EmployeeLocation.location_id.in_(body.location_ids))))
    return ids


@router.post("/courses/{course_id}/assign")
def assign(course_id: int, body: AssignIn, user: User = Depends(require("settings.manage")), db: Session = Depends(get_db)):
    """Gives the course to the chosen people, to everyone in the chosen roles or at the chosen locations. Anyone who already has it keeps their progress."""
    course = _course_or_404(db, course_id)
    if course.status != "published":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Publish the course before assigning it")
    ids = _targets(db, body)
    if not ids:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Choose who the course is for")
    if body.due_on and body.due_on < timeutil.utc_now().date():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The due date cannot be in the past")
    people = list(db.scalars(select(Employee).where(Employee.id.in_(ids), Employee.status == "active")))
    have = set(db.scalars(select(TrainingAssignment.employee_id).where(TrainingAssignment.course_id == course.id)))
    added = already = no_login = 0
    for employee in people:
        account = db.get(User, employee.user_id) if employee.user_id else None
        if account is None or not account.active:
            no_login += 1
        elif employee.id in have:
            already += 1
        else:
            made = TrainingAssignment(course_id=course.id, employee_id=employee.id, assigned_by=user.id, due_on=body.due_on)
            db.add(made)
            db.flush()
            notify(db, [account.id], "training_assigned", f"New training: {course.title}", key=f"training:{made.id}",
                   body=f"Please finish it by {body.due_on:%d %b %Y}." if body.due_on else None, link="/training")
            added += 1
    audit(db, user, "training.assign", "training_course", course.id, None,
          {"added": added, "already": already, "no_login": no_login, "due_on": body.due_on.isoformat() if body.due_on else None})
    db.commit()
    return {"assigned": added, "already_had_it": already, "without_login": no_login}


@router.delete("/assignments/{assignment_id}")
def unassign(assignment_id: int, user: User = Depends(require("settings.manage")), db: Session = Depends(get_db)):
    assignment = db.get(TrainingAssignment, assignment_id)
    if not assignment:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assignment not found")
    if assignment.completed_at:
        raise HTTPException(status.HTTP_409_CONFLICT, "Completed training stays on record")
    db.execute(delete(TrainingProgress).where(TrainingProgress.assignment_id == assignment.id))
    db.execute(delete(TrainingAttempt).where(TrainingAttempt.assignment_id == assignment.id))
    audit(db, user, "training.unassign", "training_course", assignment.course_id, {"employee_id": assignment.employee_id}, None)
    db.delete(assignment)
    db.commit()
    return {"deleted": assignment_id}


def _progress_rows(db: Session, course_id: int | None) -> list[dict]:
    stmt = (select(TrainingAssignment, TrainingCourse, Employee).join(TrainingCourse, TrainingCourse.id == TrainingAssignment.course_id)
            .join(Employee, Employee.id == TrainingAssignment.employee_id))
    if course_id is not None:
        stmt = stmt.where(TrainingAssignment.course_id == course_id)
    found = db.execute(stmt.order_by(TrainingCourse.title, Employee.full_name)).all()
    if not found:
        return []
    ids = [a.id for a, _, _ in found]
    lessons = dict(db.execute(select(TrainingLesson.course_id, func.count()).group_by(TrainingLesson.course_id)).all())
    done = dict(db.execute(select(TrainingProgress.assignment_id, func.count()).where(
        TrainingProgress.completed_at.is_not(None), TrainingProgress.assignment_id.in_(ids)).group_by(TrainingProgress.assignment_id)).all())
    last = dict(db.execute(select(TrainingProgress.assignment_id, func.max(TrainingProgress.updated_at)).where(
        TrainingProgress.assignment_id.in_(ids)).group_by(TrainingProgress.assignment_id)).all())
    places: dict[int, list[str]] = {}
    for employee_id, place in db.execute(select(EmployeeLocation.employee_id, Location.name).join(Location, Location.id == EmployeeLocation.location_id)
                                         .where(EmployeeLocation.employee_id.in_({e.id for _, _, e in found})).order_by(Location.name)):
        places.setdefault(employee_id, []).append(place)
    today = timeutil.utc_now().date()
    rows = []
    for assignment, course, employee in found:
        finished = done.get(assignment.id, 0)
        total = lessons.get(course.id, 0)
        state, overdue = engine.status_of(assignment, finished, today)
        rows.append({"assignment_id": assignment.id, "course_id": course.id, "course": course.title, "employee_id": employee.id,
                     "employee": employee.full_name, "employee_code": employee.employee_code, "job_title": employee.job_title,
                     "locations": places.get(employee.id, []), "status": state, "overdue": overdue, "lessons": total, "done": finished,
                     "percent": round(100 * finished / total) if total else 0,
                     "assigned_at": assignment.assigned_at.isoformat(), "due_on": assignment.due_on.isoformat() if assignment.due_on else None,
                     "started_at": assignment.started_at.isoformat() if assignment.started_at else None,
                     "last_activity": last[assignment.id].isoformat() if last.get(assignment.id) else None,
                     "completed_at": assignment.completed_at.isoformat() if assignment.completed_at else None,
                     "score": assignment.score, "certificate_no": assignment.certificate_no})
    return rows


@router.get("/progress")
def progress(course_id: int | None = None, user: User = Depends(require("settings.manage")), db: Session = Depends(get_db)):
    """Who has which course and how far they are, for one course or all of them."""
    rows = _progress_rows(db, course_id)
    return {"items": rows, "summary": {"assigned": len(rows), "completed": sum(1 for r in rows if r["status"] == "completed"),
                                       "in_progress": sum(1 for r in rows if r["status"] == "in_progress"),
                                       "not_started": sum(1 for r in rows if r["status"] == "not_started"),
                                       "overdue": sum(1 for r in rows if r["overdue"])}}


@router.get("/progress.csv")
def progress_csv(course_id: int | None = None, user: User = Depends(require("settings.manage")), db: Session = Depends(get_db)):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Course", "Employee", "Code", "Job title", "Locations", "Assigned", "Due", "Status", "Overdue", "Lessons done", "Lessons",
                     "Progress %", "Started", "Last activity", "Completed", "Quiz result %", "Certificate"])
    for r in _progress_rows(db, course_id):
        writer.writerow([r["course"], r["employee"], r["employee_code"], r["job_title"], ", ".join(r["locations"]), r["assigned_at"][:10],
                         r["due_on"] or "", r["status"].replace("_", " "), "yes" if r["overdue"] else "", r["done"], r["lessons"], r["percent"],
                         (r["started_at"] or "")[:10], (r["last_activity"] or "")[:10], (r["completed_at"] or "")[:10],
                         "" if r["score"] is None else r["score"], r["certificate_no"] or ""])
    return Response("﻿" + buffer.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="training-progress.csv"'})


@router.get("/assignments/{assignment_id}/certificate")
def admin_certificate(assignment_id: int, user: User = Depends(require("settings.manage")), db: Session = Depends(get_db)):
    assignment = db.get(TrainingAssignment, assignment_id)
    if not assignment or not assignment.completed_at or not assignment.certificate_no:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "There is no certificate for this training")
    pdf = engine.certificate_pdf(db, assignment, db.get(TrainingCourse, assignment.course_id), db.get(Employee, assignment.employee_id))
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{assignment.certificate_no}.pdf"'})


# ---- videos made from slides ----------------------------------------------------------------------------------------

class SlideIn(BaseModel):
    id: str | None = Field(default=None, max_length=32)
    title: str = Field(default="", max_length=120)
    bullets: list[str] = Field(default_factory=list, max_length=slidevideo.MAX_BULLETS)
    narration: str | None = Field(default=None, max_length=3000)
    voice: Literal["none", "typed", "upload"] = "none"
    seconds: int = Field(default=6, ge=2, le=120)

    @field_validator("bullets")
    @classmethod
    def _short(cls, bullets: list[str]) -> list[str]:
        if any(len(b) > 160 for b in bullets):
            raise ValueError("A bullet point can be at most 160 characters")
        return bullets


class SlidesIn(BaseModel):
    slides: list[SlideIn] = Field(max_length=slidevideo.MAX_SLIDES)


def _video_lesson(db: Session, lesson_id: int, editing: bool = True) -> TrainingLesson:
    lesson = _lesson_or_404(db, lesson_id)
    if lesson.kind != "video":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only a video lesson can be made from slides")
    if editing and lesson.video_status in ("queued", "rendering"):
        raise HTTPException(status.HTTP_409_CONFLICT, "The video is being made; wait for it to finish")
    return lesson


def _slide_or_404(lesson: TrainingLesson, slide_id: str) -> dict:
    slide = next((s for s in lesson.slides or [] if s["id"] == slide_id), None)
    if slide is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Slide not found")
    return slide


def _changed(lesson: TrainingLesson, slides: list[dict]) -> None:
    """Stores new slides; a video already made from the old ones is now out of date."""
    lesson.slides = slides  # a fresh list, so the change is seen
    if lesson.video_status == "ready":
        lesson.video_status = "outdated"


@router.get("/voice")
def voice_status(user: User = Depends(require("settings.manage"))):
    """Whether typed voice-over can be used on this server."""
    return {"typed": voice.available()}


@router.put("/lessons/{lesson_id}/slides")
def set_slides(lesson_id: int, body: SlidesIn, user: User = Depends(require("settings.manage")), db: Session = Depends(get_db)):
    lesson = _video_lesson(db, lesson_id)
    merged, dropped = slidevideo.merge_slides(lesson.slides, [s.model_dump() for s in body.slides])
    _changed(lesson, merged)
    _course_or_404(db, lesson.course_id).updated_at = timeutil.utc_now()
    audit(db, user, "training.slides_update", "training_lesson", lesson.id, None, {"slides": len(merged)})
    db.commit()
    for name in dropped:
        _forget_file(name)
    return _lesson_dict(lesson, [])


@router.post("/lessons/{lesson_id}/slides/{slide_id}/image", status_code=201)
async def upload_slide_image(lesson_id: int, slide_id: str, file: UploadFile, user: User = Depends(require("settings.manage")),
                             db: Session = Depends(get_db)):
    lesson = _video_lesson(db, lesson_id)
    _slide_or_404(lesson, slide_id)
    name, _, _ = await _save_upload(file, slidevideo.IMAGE_TYPES, "A slide picture", limit_mb=10)
    try:
        slidevideo.check_picture(engine.media_path(name))
    except ValueError as exc:
        _forget_file(name)
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc)) from None
    slide = _slide_or_404(lesson, slide_id)
    old = slide.get("image")
    _changed(lesson, [{**s, "image": name, "image_original": (file.filename or name)[:255]} if s["id"] == slide_id else s for s in lesson.slides])
    audit(db, user, "training.slide_picture", "training_lesson", lesson.id, None, {"slide": slide_id})
    db.commit()
    _forget_file(old)
    return _lesson_dict(lesson, [])


@router.delete("/lessons/{lesson_id}/slides/{slide_id}/image")
def remove_slide_image(lesson_id: int, slide_id: str, user: User = Depends(require("settings.manage")), db: Session = Depends(get_db)):
    lesson = _video_lesson(db, lesson_id)
    old = _slide_or_404(lesson, slide_id).get("image")
    _changed(lesson, [{**s, "image": None, "image_original": None} if s["id"] == slide_id else s for s in lesson.slides])
    db.commit()
    _forget_file(old)
    return _lesson_dict(lesson, [])


@router.post("/lessons/{lesson_id}/slides/{slide_id}/audio", status_code=201)
async def upload_slide_audio(lesson_id: int, slide_id: str, file: UploadFile, user: User = Depends(require("settings.manage")),
                             db: Session = Depends(get_db)):
    """A recorded voice-over for one slide."""
    lesson = _video_lesson(db, lesson_id)
    _slide_or_404(lesson, slide_id)
    name, _, _ = await _save_upload(file, slidevideo.AUDIO_TYPES, "A voice-over")
    try:
        if slidevideo.audio_seconds(engine.media_path(name)) > 10 * 60:
            raise ValueError("A voice-over for one slide can be at most 10 minutes; split it across slides")
    except ValueError as exc:
        _forget_file(name)
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc)) from None
    except Exception:  # noqa: BLE001 - the decoder could not read it
        _forget_file(name)
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "This recording cannot be read") from None
    old = _slide_or_404(lesson, slide_id).get("audio")
    _changed(lesson, [{**s, "audio": name, "audio_original": (file.filename or name)[:255], "voice": "upload"} if s["id"] == slide_id else s
                      for s in lesson.slides])
    audit(db, user, "training.slide_voice", "training_lesson", lesson.id, None, {"slide": slide_id})
    db.commit()
    _forget_file(old)
    return _lesson_dict(lesson, [])


@router.delete("/lessons/{lesson_id}/slides/{slide_id}/audio")
def remove_slide_audio(lesson_id: int, slide_id: str, user: User = Depends(require("settings.manage")), db: Session = Depends(get_db)):
    lesson = _video_lesson(db, lesson_id)
    old = _slide_or_404(lesson, slide_id).get("audio")
    _changed(lesson, [{**s, "audio": None, "audio_original": None, "voice": "none"} if s["id"] == slide_id else s for s in lesson.slides])
    db.commit()
    _forget_file(old)
    return _lesson_dict(lesson, [])


@router.get("/lessons/{lesson_id}/slides/{slide_id}/preview.png")
def preview_slide(lesson_id: int, slide_id: str, user: User = Depends(require("settings.manage")), db: Session = Depends(get_db)):
    """How a slide will look in the video, so it can be checked before the video is made."""
    lesson = _video_lesson(db, lesson_id, editing=False)
    slides = lesson.slides or []
    slide = _slide_or_404(lesson, slide_id)
    course = _course_or_404(db, lesson.course_id)
    png = slidevideo.preview_png(slide, slides.index(slide) + 1, len(slides), course.title)
    return Response(png, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.post("/lessons/{lesson_id}/render", status_code=202)
def render_video(lesson_id: int, user: User = Depends(require("settings.manage")), db: Session = Depends(get_db)):
    """Starts making the video from the slides. It runs in the background; the lesson shows how it is getting on."""
    lesson = _video_lesson(db, lesson_id)
    issues = slidevideo.problems(lesson.slides)
    if issues:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The video cannot be made yet: " + "; ".join(issues[:3]))
    lesson.video_status, lesson.video_error = "queued", None
    audit(db, user, "training.video_render", "training_lesson", lesson.id, None, {"slides": len(lesson.slides)})
    db.commit()
    slidevideo.start(lesson.id)
    return _lesson_dict(lesson, [])


@router.get("/lessons/{lesson_id}/media-url")
def admin_media_url(lesson_id: int, user: User = Depends(require("settings.manage")), db: Session = Depends(get_db)):
    """A short-lived link so a manager can watch or listen to a lesson's file in the editor."""
    lesson = _lesson_or_404(db, lesson_id)
    if not lesson.media_name or not engine.media_path(lesson.media_name).is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This lesson has no file")
    return {"url": f"/api/training/media/{engine.make_media_token(lesson.id, user.id)}", "original": lesson.media_original,
            "type": lesson.media_type, "inline": engine.plays_inline(lesson.media_type)}
