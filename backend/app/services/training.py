"""Training: the rules for course files, playback links, progress and completion, and the certificate."""
import calendar
import hashlib
import hmac
import io
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import timeutil
from ..config import settings
from ..models import Employee, TrainingAssignment, TrainingAttempt, TrainingCourse, TrainingLesson, TrainingProgress, TrainingQuestion
from .notify import notify
from .organization import get_organization

# the file types each kind of lesson takes; the name is checked against what the file really is
MEDIA: dict[str, dict[str, str]] = {
    "video": {".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm"},
    "audio": {".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".wav": "audio/wav", ".ogg": "audio/ogg"},
    "document": {
        ".pdf": "application/pdf", ".doc": "application/msword",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".xls": "application/vnd.ms-excel",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".ppt": "application/vnd.ms-powerpoint",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation", ".csv": "text/csv", ".txt": "text/plain",
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"},
}
KINDS = ("video", "audio", "document", "text", "link", "quiz")
FILE_KINDS = tuple(MEDIA)
OLE = bytes.fromhex("D0CF11E0A1B11AE1")
MEDIA_HOURS = 6


def media_dir() -> Path:
    return Path(settings.upload_dir) / "training"


def media_path(name: str) -> Path:
    return media_dir() / name


def signature_ok(ext: str, head: bytes) -> bool:
    """Whether the first bytes of a file are what its extension says."""
    if ext in (".mp4", ".m4v", ".mov", ".m4a"):
        return head[4:8] == b"ftyp"
    if ext == ".webm":
        return head[:4] == b"\x1a\x45\xdf\xa3"
    if ext == ".mp3":
        return head[:3] == b"ID3" or (len(head) > 1 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0)
    if ext == ".wav":
        return head[:4] == b"RIFF" and head[8:12] == b"WAVE"
    if ext == ".ogg":
        return head[:4] == b"OggS"
    if ext == ".pdf":
        return head.startswith(b"%PDF")
    if ext in (".docx", ".xlsx", ".pptx"):
        return head.startswith(b"PK\x03\x04")
    if ext in (".doc", ".xls", ".ppt"):
        return head.startswith(OLE)
    if ext in (".jpg", ".jpeg"):
        return head.startswith(b"\xff\xd8\xff")
    if ext == ".png":
        return head.startswith(b"\x89PNG\r\n\x1a\n")
    if ext == ".webp":
        return head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    if ext in (".txt", ".csv"):
        return b"\x00" not in head
    return False


def plays_inline(mime: str | None) -> bool:
    """Video, sound, pictures and PDF open in the page; everything else is downloaded."""
    return bool(mime) and (mime.startswith(("video/", "audio/", "image/")) or mime == "application/pdf")


def _now_seconds() -> int:
    return calendar.timegm(timeutil.utc_now().utctimetuple())


def _signature(lesson_id: int, user_id: int, expires: int) -> str:
    return hmac.new(settings.secret_key.encode(), f"training:{lesson_id}:{user_id}:{expires}".encode(), hashlib.sha256).hexdigest()[:32]


def make_media_token(lesson_id: int, user_id: int) -> str:
    """A link a video or audio player can use, since it cannot send the sign-in header; it names one lesson and stops working after a few hours."""
    expires = _now_seconds() + MEDIA_HOURS * 3600
    return f"{lesson_id}.{user_id}.{expires}.{_signature(lesson_id, user_id, expires)}"


def read_media_token(token: str) -> int | None:
    """The lesson a genuine, unexpired link names, or None."""
    parts = token.split(".")
    if len(parts) != 4 or not all(p.isdigit() for p in parts[:3]):
        return None
    lesson_id, user_id, expires = int(parts[0]), int(parts[1]), int(parts[2])
    if expires < _now_seconds() or not hmac.compare_digest(parts[3], _signature(lesson_id, user_id, expires)):
        return None
    return lesson_id


def lessons_of(db: Session, course_id: int) -> list[TrainingLesson]:
    return list(db.scalars(select(TrainingLesson).where(TrainingLesson.course_id == course_id).order_by(TrainingLesson.position, TrainingLesson.id)))


def progress_of(db: Session, assignment_id: int) -> dict[int, TrainingProgress]:
    return {p.lesson_id: p for p in db.scalars(select(TrainingProgress).where(TrainingProgress.assignment_id == assignment_id))}


def summarise(lessons: list[TrainingLesson], progress: dict[int, TrainingProgress]) -> tuple[int, int, int]:
    """Lessons done, lessons in the course, and the percent done."""
    total = len(lessons)
    done = sum(1 for lesson in lessons if progress.get(lesson.id) and progress[lesson.id].completed_at)
    return done, total, round(100 * done / total) if total else 0


def status_of(assignment: TrainingAssignment, done: int, today: date) -> tuple[str, bool]:
    """not_started, in_progress or completed, and whether it is past its due date."""
    if assignment.completed_at:
        return "completed", False
    overdue = bool(assignment.due_on and assignment.due_on < today)
    return ("in_progress" if assignment.started_at or done else "not_started"), overdue


def publish_problems(db: Session, course: TrainingCourse) -> list[str]:
    """What stops a course being published, in words a manager can act on."""
    lessons = lessons_of(db, course.id)
    if not lessons:
        return ["Add at least one lesson"]
    problems = []
    for lesson in lessons:
        if lesson.kind in FILE_KINDS and not lesson.media_name:
            if lesson.video_status in ("queued", "rendering"):
                problems.append(f'"{lesson.title}" is still being made')
            elif lesson.slides:
                problems.append(f'"{lesson.title}" has slides but its video has not been made yet')
            else:
                problems.append(f'"{lesson.title}" needs a file')
        elif lesson.kind == "link" and not lesson.external_url:
            problems.append(f'"{lesson.title}" needs a link')
        elif lesson.kind == "text" and not (lesson.body or "").strip():
            problems.append(f'"{lesson.title}" needs some text')
        elif lesson.kind == "quiz" and not db.scalar(select(TrainingQuestion.id).where(TrainingQuestion.lesson_id == lesson.id).limit(1)):
            problems.append(f'"{lesson.title}" needs at least one question')
    return problems


def touch(db: Session, assignment: TrainingAssignment, lesson_id: int, now: datetime) -> TrainingProgress:
    progress = db.scalar(select(TrainingProgress).where(TrainingProgress.assignment_id == assignment.id, TrainingProgress.lesson_id == lesson_id))
    if progress is None:
        progress = TrainingProgress(assignment_id=assignment.id, lesson_id=lesson_id, position_seconds=0)
        db.add(progress)
    progress.updated_at = now
    assignment.started_at = assignment.started_at or now
    return progress


def complete_lesson(db: Session, assignment: TrainingAssignment, lesson_id: int, now: datetime) -> bool:
    """Marks a lesson done and finishes the course when it was the last one; returns whether the course is now complete."""
    progress = touch(db, assignment, lesson_id, now)
    progress.completed_at = progress.completed_at or now
    db.flush()
    return finish_if_done(db, assignment, now)


def finish_if_done(db: Session, assignment: TrainingAssignment, now: datetime) -> bool:
    if assignment.completed_at:
        return False
    course = db.get(TrainingCourse, assignment.course_id)
    lessons = lessons_of(db, course.id)
    done, total, _ = summarise(lessons, progress_of(db, assignment.id))
    if not total or done < total:
        return False
    assignment.completed_at = now
    if course.certificate:
        assignment.certificate_no = f"TRN-{now:%Y}-{assignment.id:05d}"
    best: dict[int, int] = {}
    for attempt in db.scalars(select(TrainingAttempt).where(TrainingAttempt.assignment_id == assignment.id, TrainingAttempt.passed.is_(True))):
        best[attempt.lesson_id] = max(best.get(attempt.lesson_id, 0), attempt.score)
    assignment.score = round(sum(best.values()) / len(best)) if best else None
    employee = db.get(Employee, assignment.employee_id)
    if employee and employee.user_id:
        notify(db, [employee.user_id], "training_done", f"Training completed: {course.title}", key=f"training-done:{assignment.id}",
               body="Well done. Your certificate is ready." if course.certificate else None, link="/training")
    return True


def _latin(text: str) -> str:
    """The PDF fonts carry Latin letters only, so anything else becomes a question mark rather than breaking the file."""
    return text.encode("latin-1", "replace").decode("latin-1")


def certificate_pdf(db: Session, assignment: TrainingAssignment, course: TrainingCourse, employee: Employee) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.utils import simpleSplit
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    width, height = landscape(A4)
    page = canvas.Canvas(buffer, pagesize=(width, height))
    navy, grey = colors.HexColor("#1d3c5d"), colors.HexColor("#5c6661")
    page.setStrokeColor(navy)
    page.setLineWidth(6)
    page.rect(30, 30, width - 60, height - 60)
    page.setLineWidth(1.2)
    page.rect(42, 42, width - 84, height - 84)
    page.setFillColor(navy)
    page.setFont("Helvetica-Bold", 36)
    page.drawCentredString(width / 2, height - 130, "Certificate of Completion")
    page.setFillColor(grey)
    page.setFont("Helvetica", 15)
    page.drawCentredString(width / 2, height - 190, "This certifies that")
    page.setFillColor(colors.black)
    page.setFont("Helvetica-Bold", 30)
    page.drawCentredString(width / 2, height - 240, _latin(employee.full_name))
    page.setFillColor(grey)
    page.setFont("Helvetica", 15)
    page.drawCentredString(width / 2, height - 285, "has successfully completed the training course")
    page.setFillColor(navy)
    page.setFont("Helvetica-Bold", 24)
    y = height - 335
    for line in simpleSplit(_latin(course.title), "Helvetica-Bold", 24, width - 160)[:3]:
        page.drawCentredString(width / 2, y, line)
        y -= 32
    page.setFillColor(grey)
    page.setFont("Helvetica", 13)
    details = [f"Completed on {assignment.completed_at:%d %B %Y}"]
    if assignment.score is not None:
        details.append(f"Quiz result {assignment.score}%")
    page.drawCentredString(width / 2, 150, _latin("   |   ".join(details)))
    page.setFont("Helvetica", 11)
    page.drawCentredString(width / 2, 120, f"Certificate number {assignment.certificate_no}")
    page.drawCentredString(width / 2, 98, _latin(get_organization(db).get("name") or ""))
    page.showPage()
    page.save()
    return buffer.getvalue()
