"""Makes a training video from slides: text and pictures on a branded background, with a typed or recorded voice-over.

The result is an ordinary MP4 (H.264 and AAC) that plays in any browser. Encoding uses the encoder inside the PyAV package, so the
server needs no separate video software, and nothing is sent to an outside service.
"""
import io
import logging
import re
import threading
import uuid
from pathlib import Path

import av
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps
from sqlalchemy import update
from sqlalchemy.orm import Session

from ..audit import audit
from ..db import SessionLocal
from ..models import TrainingCourse, TrainingLesson
from . import training as engine
from . import voice

log = logging.getLogger(__name__)

WIDTH, HEIGHT, FPS, RATE = 1280, 720, 12, 44100
FADE_FRAMES = 5  # the short dissolve from one slide to the next
LEAD_SECONDS, TAIL_SECONDS = 0.5, 0.8  # a breath before and after a voice-over
MAX_SLIDES, MAX_BULLETS, MAX_MINUTES = 40, 8, 30
IMAGE_TYPES = {ext: mime for ext, mime in engine.MEDIA["document"].items() if mime.startswith("image/")}
AUDIO_TYPES = engine.MEDIA["audio"]
MAX_PIXELS = 40_000_000  # a picture bigger than this is refused rather than risk filling the server's memory

NAVY_TOP, NAVY_BOTTOM = (29, 60, 93), (13, 42, 71)
ACCENTS = [(242, 182, 50), (109, 191, 166), (238, 106, 74)]
WHITE, SOFT, FAINT = (255, 255, 255), (222, 232, 242), (150, 176, 200)

_render_gate = threading.Semaphore(1)  # one video at a time; the server is small


def new_id() -> str:
    return uuid.uuid4().hex[:12]


# ---- the slides as stored -------------------------------------------------------------------------------------------

def merge_slides(existing: list[dict] | None, incoming: list[dict]) -> tuple[list[dict], list[str]]:
    """The slides as saved: the words from the form, the pictures and recordings kept from before.

    Also returns the stored files nothing uses any more, so they can be deleted.
    """
    before_by_id = {s["id"]: s for s in existing or []}
    result = []
    for item in incoming:
        before = before_by_id.get(item.get("id")) or {}
        voice_kind = item.get("voice", "none")
        result.append({
            "id": before.get("id") or new_id(),
            "title": " ".join((item.get("title") or "").split()),
            "bullets": [" ".join(b.split()) for b in item.get("bullets") or [] if b and b.strip()][:MAX_BULLETS],
            "narration": (item.get("narration") or "").strip() or None,
            "voice": voice_kind,
            "seconds": int(item.get("seconds") or 6),
            "image": before.get("image"), "image_original": before.get("image_original"),
            # a recording only stays while the slide is set to use one
            "audio": before.get("audio") if voice_kind == "upload" else None,
            "audio_original": before.get("audio_original") if voice_kind == "upload" else None,
        })
    used = asset_names(result)
    dropped = [name for old in before_by_id.values() for name in (old.get("image"), old.get("audio")) if name and name not in used]
    return result, dropped


def asset_names(slides: list[dict] | None) -> set[str]:
    return {name for s in slides or [] for name in (s.get("image"), s.get("audio")) if name}


def problems(slides: list[dict] | None) -> list[str]:
    """What stops these slides becoming a video, in words a manager can act on."""
    if not slides:
        return ["Add at least one slide"]
    found = []
    for number, slide in enumerate(slides, start=1):
        if not (slide.get("title") or slide.get("bullets") or slide.get("image")):
            found.append(f"Slide {number} is empty")
        if slide.get("voice") == "typed":
            if not (slide.get("narration") or "").strip():
                found.append(f"Slide {number}: type what should be said, or choose no voice-over")
            elif not voice.available():
                found.append("Typed voice-over is not set up on this server; upload a recording instead")
        elif slide.get("voice") == "upload" and not slide.get("audio"):
            found.append(f"Slide {number}: upload the recording, or choose no voice-over")
    return found


# ---- drawing a slide ------------------------------------------------------------------------------------------------

_fonts: dict[tuple[int, bool], ImageFont.FreeTypeFont] = {}


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    if (size, bold) not in _fonts:
        import reportlab

        base = Path(reportlab.__file__).parent / "fonts"  # Bitstream Vera, shipped with the PDF library
        _fonts[(size, bold)] = ImageFont.truetype(str(base / ("VeraBd.ttf" if bold else "Vera.ttf")), size)
    return _fonts[(size, bold)]


def _wrap(text: str, fnt: ImageFont.FreeTypeFont, width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.split("\n"):
        line = ""
        for word in paragraph.split():
            trial = f"{line} {word}".strip()
            if fnt.getlength(trial) <= width or not line:
                line = trial
            else:
                lines.append(line)
                line = word
        lines.append(line)
    return lines


_background: Image.Image | None = None


def _backdrop() -> Image.Image:
    global _background
    if _background is None:
        top, bottom = np.array(NAVY_TOP, dtype=np.float32), np.array(NAVY_BOTTOM, dtype=np.float32)
        ramp = np.linspace(0, 1, HEIGHT, dtype=np.float32)[:, None, None]
        column = (top + (bottom - top) * ramp).astype(np.uint8)
        _background = Image.fromarray(np.repeat(column, WIDTH, axis=1), "RGB")
    return _background.copy()


def load_picture(slide: dict) -> Image.Image | None:
    name = slide.get("image")
    path = engine.media_path(name) if name else None
    if not path or not path.is_file():
        return None
    with Image.open(path) as opened:
        picture = ImageOps.exif_transpose(opened)
        if picture.mode in ("RGBA", "LA", "P"):
            rgba = picture.convert("RGBA")
            flat = Image.new("RGB", rgba.size, WHITE)
            flat.paste(rgba, mask=rgba.split()[3])
            return flat
        return picture.convert("RGB")


def slide_image(slide: dict, number: int, total: int, course_title: str, picture: Image.Image | None) -> Image.Image:
    """One slide as a 1280 by 720 picture."""
    img = _backdrop()
    draw = ImageDraw.Draw(img)
    for index, colour in enumerate(ACCENTS):
        draw.rectangle([0, index * HEIGHT // 3, 13, (index + 1) * HEIGHT // 3], fill=colour)

    title, bullets = slide.get("title") or "", slide.get("bullets") or []
    left = 84
    if title and not bullets and not picture:  # a title slide: big and centred
        for size in range(84, 43, -6):
            fnt = font(size, True)
            lines = _wrap(title, fnt, WIDTH - 220)
            if len(lines) <= 4:
                break
        line_h = int(size * 1.25)
        y = (HEIGHT - len(lines) * line_h) // 2 - 20
        for line in lines[:4]:
            draw.text(((WIDTH - fnt.getlength(line)) / 2, y), line, font=fnt, fill=WHITE)
            y += line_h
        draw.rectangle([WIDTH // 2 - 70, y + 14, WIDTH // 2 + 70, y + 22], fill=ACCENTS[0])
    else:
        text_width = 600 if picture else WIDTH - 2 * left
        y = 78
        if title:
            for size in range(58, 33, -4):
                fnt = font(size, True)
                lines = _wrap(title, fnt, text_width)
                if len(lines) <= 3:
                    break
            line_h = int(size * 1.22)
            for line in lines[:3]:
                draw.text((left, y), line, font=fnt, fill=WHITE)
                y += line_h
            draw.rectangle([left, y + 8, left + 90, y + 14], fill=ACCENTS[0])
            y += 44
        if bullets:
            room = HEIGHT - 96 - y
            for size in (36, 33, 30, 28, 26, 24):
                fnt = font(size)
                line_h = int(size * 1.28)
                wrapped = [_wrap(b, fnt, text_width - 46) for b in bullets]
                if sum(len(w) * line_h + 16 for w in wrapped) <= room:
                    break
            for lines in wrapped:
                if y + len(lines) * line_h > HEIGHT - 96:
                    draw.text((left + 46, y), "...", font=fnt, fill=SOFT)
                    break
                draw.rounded_rectangle([left + 4, y + line_h // 2 - 6, left + 16, y + line_h // 2 + 6], radius=3, fill=ACCENTS[1])
                for line in lines:
                    draw.text((left + 46, y), line, font=fnt, fill=SOFT)
                    y += line_h
                y += 16
        if picture:
            box = (676, 100, 1216, 600)
            draw.rounded_rectangle(box, radius=22, fill=(236, 242, 248))
            fitted = ImageOps.contain(picture, (box[2] - box[0] - 28, box[3] - box[1] - 28))
            img.paste(fitted, (box[0] + (box[2] - box[0] - fitted.width) // 2, box[1] + (box[3] - box[1] - fitted.height) // 2))

    small = font(21)
    draw.text((left, HEIGHT - 52), course_title[:70], font=small, fill=FAINT)
    page = f"{number} / {total}"
    draw.text((WIDTH - 60 - small.getlength(page), HEIGHT - 52), page, font=small, fill=FAINT)
    return img


def preview_png(slide: dict, number: int, total: int, course_title: str) -> bytes:
    buffer = io.BytesIO()
    slide_image(slide, number, total, course_title, load_picture(slide)).save(buffer, "PNG")
    return buffer.getvalue()


def check_picture(path: Path) -> None:
    """Refuses a file that is not a real, reasonably sized picture."""
    try:
        with Image.open(path) as opened:
            opened.verify()
        with Image.open(path) as opened:
            too_big = opened.width * opened.height > MAX_PIXELS
    except Exception as exc:  # noqa: BLE001 - whatever the picture library says, it is not a usable picture
        raise ValueError("This is not a picture that can be read") from exc
    if too_big:
        raise ValueError("This picture is too large; use one under 40 megapixels")


# ---- sound ----------------------------------------------------------------------------------------------------------

def audio_seconds(source: Path) -> float:
    """How long a recording is; raises when it cannot be decoded."""
    with av.open(str(source)) as container:
        if not container.streams.audio:
            raise ValueError("This file has no sound")
        if container.duration:
            return container.duration / av.time_base
        seconds = 0.0
        for frame in container.decode(audio=0):
            seconds += frame.samples / frame.sample_rate
        return seconds


def _chunks(source: Path):
    """The recording as 44.1 kHz stereo pieces, so a long one never sits whole in memory."""
    with av.open(str(source)) as container:
        resampler = av.AudioResampler(format="fltp", layout="stereo", rate=RATE)
        for frame in container.decode(audio=0):
            for piece in resampler.resample(frame):
                yield piece.to_ndarray()
        for piece in resampler.resample(None):
            yield piece.to_ndarray()


class Writer:
    """An MP4 being written, a frame or a few samples at a time."""

    def __init__(self, target: Path):
        self.out = av.open(str(target), "w", format="mp4", options={"movflags": "+faststart"})
        self.video = self.out.add_stream("libx264", rate=FPS)
        self.video.width, self.video.height, self.video.pix_fmt = WIDTH, HEIGHT, "yuv420p"
        self.video.options = {"preset": "veryfast", "crf": "27", "tune": "stillimage"}
        self.video.codec_context.gop_size = FPS * 2
        self.audio = self.out.add_stream("aac", rate=RATE)
        self.audio.layout = "stereo"
        self.frames = 0
        self.samples = 0

    def picture(self, image: Image.Image) -> None:
        frame = av.VideoFrame.from_image(image)
        frame.pts = self.frames
        self.frames += 1
        for packet in self.video.encode(frame):
            self.out.mux(packet)

    def sound(self, block: np.ndarray) -> None:
        frame = av.AudioFrame.from_ndarray(np.ascontiguousarray(block, dtype=np.float32), format="fltp", layout="stereo")
        frame.sample_rate = RATE
        frame.pts = self.samples
        self.samples += block.shape[1]
        for packet in self.audio.encode(frame):
            self.out.mux(packet)

    def silence(self, samples: int) -> None:
        while samples > 0:
            step = min(samples, RATE * 5)
            self.sound(np.zeros((2, step), dtype=np.float32))
            samples -= step

    def close(self) -> None:
        for stream in (self.video, self.audio):
            for packet in stream.encode():
                self.out.mux(packet)
        self.out.close()

    def abort(self) -> None:
        try:
            self.out.close()
        except Exception:  # noqa: BLE001 - already failing; the file is thrown away
            pass


def _slide_sound(writer: Writer, source: Path | None, samples: int) -> None:
    """One slide's worth of sound: a breath of quiet, the voice-over, then quiet to the slide's end."""
    lead = min(round(LEAD_SECONDS * RATE) if source else 0, samples)
    writer.silence(lead)
    written = lead
    if source:
        for block in _chunks(source):
            block = block[:, : samples - written]
            if block.shape[1]:
                writer.sound(block)
                written += block.shape[1]
            if written >= samples:
                break
    writer.silence(samples - written)


def render(slides: list[dict], course_title: str, target: Path) -> None:
    """Writes the video for these slides to `target`."""
    plan: list[tuple[Image.Image, Path | None, float]] = []
    temporary: list[Path] = []
    try:
        for index, slide in enumerate(slides):
            image = slide_image(slide, index + 1, len(slides), course_title, load_picture(slide))
            source: Path | None = None
            if slide.get("voice") == "upload" and slide.get("audio"):
                source = engine.media_path(slide["audio"])
            elif slide.get("voice") == "typed" and (slide.get("narration") or "").strip():
                source = engine.media_dir() / f".speech-{uuid.uuid4().hex}.wav"
                source.write_bytes(voice.synthesize(slide["narration"]))
                temporary.append(source)
            seconds = audio_seconds(source) + LEAD_SECONDS + TAIL_SECONDS if source else float(slide.get("seconds") or 6)
            plan.append((image, source, seconds))
        if sum(item[2] for item in plan) > MAX_MINUTES * 60:
            raise ValueError(f"The video would be longer than {MAX_MINUTES} minutes")

        writer = Writer(target)
        try:
            previous: Image.Image | None = None
            for image, source, seconds in plan:
                frames = max(2, round(seconds * FPS))
                fade = min(FADE_FRAMES, frames - 1) if previous is not None else 0
                for n in range(frames):
                    writer.picture(Image.blend(previous, image, (n + 1) / (fade + 1)) if n < fade else image)
                _slide_sound(writer, source, round(frames / FPS * RATE))
                previous = image
            writer.close()
        except Exception:
            writer.abort()
            raise
    finally:
        for path in temporary:
            path.unlink(missing_ok=True)


# ---- the background job ---------------------------------------------------------------------------------------------

def start(lesson_id: int) -> None:
    threading.Thread(target=run, args=(lesson_id,), daemon=True).start()


def _file_name(title: str) -> str:
    return (re.sub(r"[^A-Za-z0-9 _.-]", "", title).strip() or "video")[:80] + ".mp4"


def run(lesson_id: int) -> None:
    """Makes the video for a lesson that was queued, and records how it went. Never raises: the manager reads the outcome on the lesson."""
    with _render_gate, SessionLocal() as db:
        lesson = db.get(TrainingLesson, lesson_id)
        if not lesson or lesson.video_status != "queued":
            return
        lesson.video_status = "rendering"
        db.commit()
        engine.media_dir().mkdir(parents=True, exist_ok=True)
        target = engine.media_dir() / f"{uuid.uuid4().hex}.mp4"
        try:
            course = db.get(TrainingCourse, lesson.course_id)
            render(lesson.slides or [], course.title, target)
            db.refresh(lesson)
            old = lesson.media_name
            lesson.media_name, lesson.media_original = target.name, _file_name(lesson.title)
            lesson.media_type, lesson.media_size = "video/mp4", target.stat().st_size
            lesson.video_status, lesson.video_error = "ready", None
            audit(db, None, "training.video_rendered", "training_lesson", lesson.id, None, {"slides": len(lesson.slides or []), "bytes": lesson.media_size})
            db.commit()
            if old:
                engine.media_path(old).unlink(missing_ok=True)
        except Exception as exc:  # noqa: BLE001 - every failure is reported on the lesson
            log.exception("making the video for lesson %s failed", lesson_id)
            target.unlink(missing_ok=True)
            db.rollback()
            lesson = db.get(TrainingLesson, lesson_id)
            if lesson:
                lesson.video_status, lesson.video_error = "failed", (str(exc) or exc.__class__.__name__)[:290]
                db.commit()


def fail_interrupted(db: Session) -> int:
    """A restart kills a video that was being made; say so instead of leaving it saying "rendering" forever."""
    result = db.execute(update(TrainingLesson).where(TrainingLesson.video_status.in_(("queued", "rendering")))
                        .values(video_status="failed", video_error="The server restarted while the video was being made. Make it again."))
    return result.rowcount
