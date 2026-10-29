from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import timeutil
from ..db import get_db
from ..deps import require
from ..models import (Employee, TrainingAssignment, TrainingAttempt, TrainingCourse, TrainingLesson, TrainingProgress,
                      TrainingQuestion, User)
from ..services import training as engine

router = APIRouter(prefix="/api/training", tags=["training"])


def _employee(user: User) -> Employee:
    if not user.employee:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No employee profile on this account")
    return user.employee


def _mine(db: Session, user: User, assignment_id: int) -> tuple[TrainingAssignment, TrainingCourse]:
    employee = _employee(user)
    assignment = db.get(TrainingAssignment, assignment_id)
    if not assignment or assignment.employee_id != employee.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Training not found")
    course = db.get(TrainingCourse, assignment.course_id)
    if course.status != "published":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Training not found")
    return assignment, course


def _lesson_in(db: Session, course: TrainingCourse, lesson_id: int) -> TrainingLesson:
    lesson = db.get(TrainingLesson, lesson_id)
    if not lesson or lesson.course_id != course.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lesson not found")
    return lesson


def _today() -> date:
    return timeutil.utc_now().date()


def _summary(assignment: TrainingAssignment, course: TrainingCourse, lessons: list, progress: dict) -> dict:
    done, total, percent = engine.summarise(lessons, progress)
    state, overdue = engine.status_of(assignment, done, _today())
    return {"assignment_id": assignment.id, "course_id": course.id, "title": course.title, "description": course.description,
            "category": course.category, "lessons": total, "done": done, "percent": percent, "status": state, "overdue": overdue,
            "due_on": assignment.due_on.isoformat() if assignment.due_on else None, "assigned_at": assignment.assigned_at.isoformat(),
            "started_at": assignment.started_at.isoformat() if assignment.started_at else None,
            "completed_at": assignment.completed_at.isoformat() if assignment.completed_at else None,
            "score": assignment.score, "certificate": bool(assignment.certificate_no)}


@router.get("/my")
def my_training(user: User = Depends(require("training.view")), db: Session = Depends(get_db)):
    """Every published course assigned to the signed-in person, with how far they have got."""
    if not user.employee:
        return {"items": []}
    rows = db.execute(select(TrainingAssignment, TrainingCourse).join(TrainingCourse, TrainingCourse.id == TrainingAssignment.course_id)
                      .where(TrainingAssignment.employee_id == user.employee.id, TrainingCourse.status == "published")).all()
    lessons: dict[int, list] = {}
    progress: dict[int, dict] = {}
    if rows:
        for lesson in db.scalars(select(TrainingLesson).where(TrainingLesson.course_id.in_({c.id for _, c in rows}))):
            lessons.setdefault(lesson.course_id, []).append(lesson)
        for p in db.scalars(select(TrainingProgress).where(TrainingProgress.assignment_id.in_({a.id for a, _ in rows}))):
            progress.setdefault(p.assignment_id, {})[p.lesson_id] = p
    items = [_summary(a, c, lessons.get(c.id, []), progress.get(a.id, {})) for a, c in rows]
    # what still needs doing comes first, the nearest due date at the top; finished courses follow
    items.sort(key=lambda i: (i["status"] == "completed", i["due_on"] is None, i["due_on"] or "", i["title"].lower()))
    return {"items": items}


@router.get("/my/{assignment_id}")
def my_course(assignment_id: int, user: User = Depends(require("training.view")), db: Session = Depends(get_db)):
    assignment, course = _mine(db, user, assignment_id)
    lessons = engine.lessons_of(db, course.id)
    progress = engine.progress_of(db, assignment.id)
    asked: dict[int, int] = {}
    if lessons:
        for lesson_id, in db.execute(select(TrainingQuestion.lesson_id).where(TrainingQuestion.lesson_id.in_([lesson.id for lesson in lessons]))):
            asked[lesson_id] = asked.get(lesson_id, 0) + 1
    out = []
    for lesson in lessons:
        p = progress.get(lesson.id)
        out.append({"id": lesson.id, "title": lesson.title, "kind": lesson.kind, "body": lesson.body, "external_url": lesson.external_url,
                    "media": {"original": lesson.media_original, "type": lesson.media_type, "size": lesson.media_size,
                              "inline": engine.plays_inline(lesson.media_type)} if lesson.media_name else None,
                    "completed": bool(p and p.completed_at), "position_seconds": p.position_seconds if p else 0,
                    "questions": asked.get(lesson.id, 0)})
    return {**_summary(assignment, course, lessons, progress), "pass_mark": course.pass_mark, "lesson_list": out}


class PositionIn(BaseModel):
    position_seconds: int = Field(ge=0, le=259200)


@router.post("/my/{assignment_id}/lessons/{lesson_id}/position")
def save_position(assignment_id: int, lesson_id: int, body: PositionIn, user: User = Depends(require("training.view")),
                  db: Session = Depends(get_db)):
    """Remembers where a video or audio was left, so it picks up from there."""
    assignment, course = _mine(db, user, assignment_id)
    _lesson_in(db, course, lesson_id)
    engine.touch(db, assignment, lesson_id, timeutil.utc_now()).position_seconds = body.position_seconds
    db.commit()
    return {"ok": True}


def _after(db: Session, assignment: TrainingAssignment, course: TrainingCourse, finished: bool) -> dict:
    lessons = engine.lessons_of(db, course.id)
    return {**_summary(assignment, course, lessons, engine.progress_of(db, assignment.id)), "course_completed": finished}


@router.post("/my/{assignment_id}/lessons/{lesson_id}/complete")
def complete(assignment_id: int, lesson_id: int, user: User = Depends(require("training.view")), db: Session = Depends(get_db)):
    assignment, course = _mine(db, user, assignment_id)
    lesson = _lesson_in(db, course, lesson_id)
    if lesson.kind == "quiz":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Pass the quiz to finish this lesson")
    finished = engine.complete_lesson(db, assignment, lesson.id, timeutil.utc_now())
    db.commit()
    return _after(db, assignment, course, finished)


@router.get("/my/{assignment_id}/lessons/{lesson_id}/media-url")
def media_url(assignment_id: int, lesson_id: int, user: User = Depends(require("training.view")), db: Session = Depends(get_db)):
    assignment, course = _mine(db, user, assignment_id)
    lesson = _lesson_in(db, course, lesson_id)
    if not lesson.media_name or not engine.media_path(lesson.media_name).is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This lesson has no file")
    return {"url": f"/api/training/media/{engine.make_media_token(lesson.id, user.id)}", "original": lesson.media_original,
            "type": lesson.media_type, "inline": engine.plays_inline(lesson.media_type)}


@router.get("/media/{token}")
def media(token: str, db: Session = Depends(get_db)):
    """Streams a lesson's file to a player. The link is signed and short-lived, so a video element, which cannot send headers, can use it."""
    lesson_id = engine.read_media_token(token)
    lesson = db.get(TrainingLesson, lesson_id) if lesson_id else None
    if not lesson or not lesson.media_name or not engine.media_path(lesson.media_name).is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    return FileResponse(engine.media_path(lesson.media_name), media_type=lesson.media_type, filename=lesson.media_original,
                        content_disposition_type="inline" if engine.plays_inline(lesson.media_type) else "attachment")


def _quiz_lesson(db: Session, course: TrainingCourse, lesson_id: int) -> tuple[TrainingLesson, list[TrainingQuestion]]:
    lesson = _lesson_in(db, course, lesson_id)
    if lesson.kind != "quiz":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This lesson is not a quiz")
    questions = list(db.scalars(select(TrainingQuestion).where(TrainingQuestion.lesson_id == lesson.id).order_by(TrainingQuestion.position, TrainingQuestion.id)))
    return lesson, questions


@router.get("/my/{assignment_id}/lessons/{lesson_id}/quiz")
def quiz(assignment_id: int, lesson_id: int, user: User = Depends(require("training.view")), db: Session = Depends(get_db)):
    assignment, course = _mine(db, user, assignment_id)
    lesson, questions = _quiz_lesson(db, course, lesson_id)
    attempts = list(db.scalars(select(TrainingAttempt).where(TrainingAttempt.assignment_id == assignment.id, TrainingAttempt.lesson_id == lesson.id)))
    return {"pass_mark": course.pass_mark, "attempts": len(attempts), "best": max((a.score for a in attempts), default=None),
            "passed": any(a.passed for a in attempts),
            "questions": [{"id": q.id, "text": q.text, "options": q.options} for q in questions]}


class QuizAnswersIn(BaseModel):
    answers: list[int | None] = Field(max_length=100)


@router.post("/my/{assignment_id}/lessons/{lesson_id}/quiz")
def submit_quiz(assignment_id: int, lesson_id: int, body: QuizAnswersIn, user: User = Depends(require("training.view")),
                db: Session = Depends(get_db)):
    """Marks the answers. Passing finishes the lesson; trying again is always allowed."""
    assignment, course = _mine(db, user, assignment_id)
    lesson, questions = _quiz_lesson(db, course, lesson_id)
    if not questions or len(body.answers) != len(questions):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Answer every question")
    results = [answer is not None and answer == q.correct for answer, q in zip(body.answers, questions)]
    score = round(100 * sum(results) / len(questions))
    passed = score >= course.pass_mark
    now = timeutil.utc_now()
    db.add(TrainingAttempt(assignment_id=assignment.id, lesson_id=lesson.id, score=score, passed=passed, answers=body.answers))
    engine.touch(db, assignment, lesson.id, now)
    finished = False
    if passed:
        db.flush()
        finished = engine.complete_lesson(db, assignment, lesson.id, now)
    db.commit()
    return {**_after(db, assignment, course, finished), "score": score, "passed": passed, "correct": sum(results),
            "total": len(questions), "results": results}


@router.get("/my/{assignment_id}/certificate")
def certificate(assignment_id: int, user: User = Depends(require("training.view")), db: Session = Depends(get_db)):
    assignment, course = _mine(db, user, assignment_id)
    if not assignment.completed_at or not assignment.certificate_no:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "There is no certificate for this training")
    pdf = engine.certificate_pdf(db, assignment, course, _employee(user))
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{assignment.certificate_no}.pdf"'})
