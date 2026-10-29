from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from .core import ts


class TrainingCourse(Base):
    """A course is an ordered list of lessons; only a published course can be assigned."""

    __tablename__ = "training_course"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(12), default="draft")  # draft | published
    pass_mark: Mapped[int] = mapped_column(Integer, default=80)  # percent a quiz needs
    certificate: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("user.id"))
    created_at: Mapped[datetime] = ts()
    updated_at: Mapped[datetime] = ts()


class TrainingLesson(Base):
    __tablename__ = "training_lesson"
    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("training_course.id"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(12))  # video | audio | document | text | link | quiz
    body: Mapped[str | None] = mapped_column(Text)  # the text of a text lesson, or notes shown with any other
    external_url: Mapped[str | None] = mapped_column(String(500))  # a link lesson opens this address
    media_name: Mapped[str | None] = mapped_column(String(60))  # the stored file; people see media_original
    media_original: Mapped[str | None] = mapped_column(String(255))
    media_type: Mapped[str | None] = mapped_column(String(100))
    media_size: Mapped[int | None] = mapped_column(Integer)
    slides: Mapped[list | None] = mapped_column(JSON)  # a video made from slides: each slide's text, picture and voice-over
    video_status: Mapped[str | None] = mapped_column(String(10))  # queued | rendering | ready | outdated | failed
    video_error: Mapped[str | None] = mapped_column(String(300))


class TrainingQuestion(Base):
    __tablename__ = "training_question"
    id: Mapped[int] = mapped_column(primary_key=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("training_lesson.id"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(String(500))
    options: Mapped[list] = mapped_column(JSON)  # the answers shown, in order
    correct: Mapped[int] = mapped_column(Integer)  # index of the right answer


class TrainingAssignment(Base):
    """One person taking one course; its progress and certificate hang off it."""

    __tablename__ = "training_assignment"
    __table_args__ = (UniqueConstraint("course_id", "employee_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("training_course.id"), index=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employee.id"), index=True)
    assigned_by: Mapped[int] = mapped_column(ForeignKey("user.id"))
    assigned_at: Mapped[datetime] = ts()
    due_on: Mapped[date | None] = mapped_column(Date)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    certificate_no: Mapped[str | None] = mapped_column(String(30), unique=True)
    score: Mapped[int | None] = mapped_column(Integer)  # average of the quiz results, when the course had quizzes


class TrainingProgress(Base):
    __tablename__ = "training_progress"
    __table_args__ = (UniqueConstraint("assignment_id", "lesson_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey("training_assignment.id"), index=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("training_lesson.id"), index=True)
    position_seconds: Mapped[int] = mapped_column(Integer, default=0)  # where a video or audio was left
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = ts()


class TrainingAttempt(Base):
    __tablename__ = "training_attempt"
    id: Mapped[int] = mapped_column(primary_key=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey("training_assignment.id"), index=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("training_lesson.id"), index=True)
    score: Mapped[int] = mapped_column(Integer)
    passed: Mapped[bool] = mapped_column(Boolean)
    answers: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = ts()
