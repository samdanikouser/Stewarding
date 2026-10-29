import io
import math
import struct
import wave

import av
from PIL import Image
from sqlalchemy import select

from app.models import AuditLog, TrainingLesson
from app.services import slidevideo, voice
from app.services import training as engine

from .helpers import MGR, STEWARD
from .test_training import URL, add_lesson, stored


def tone(seconds: float, hertz: int = 330) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16000)
        out.writeframes(b"".join(struct.pack("<h", int(6000 * math.sin(2 * math.pi * hertz * n / 16000))) for n in range(int(16000 * seconds))))
    return buffer.getvalue()


def picture(colour=(200, 60, 60)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (320, 200), colour).save(buffer, "PNG")
    return buffer.getvalue()


def lesson_of(client, h, course_id, lesson_id):
    return next(item for item in client.get(f"{URL}/courses/{course_id}", headers=h).json()["lesson_list"] if item["id"] == lesson_id)


def three_slides():
    return [
        {"title": "Cold storage basics", "voice": "none", "seconds": 2},
        {"title": "Fridge rules", "bullets": ["Keep it below 5 degrees", "Raw food goes on the bottom shelf"], "voice": "none", "seconds": 2},
        {"title": "Check the log", "bullets": ["Record the temperature twice a day"], "narration": "Always record the temperature twice a day.", "voice": "typed"},
    ]


def setup(client, h, monkeypatch, typed_voice=True):
    """A course with an empty video lesson; renders run on the spot, and a stand-in voice reads one second of tone."""
    monkeypatch.setattr(slidevideo, "start", slidevideo.run)
    if typed_voice:
        monkeypatch.setattr(voice, "available", lambda: True)
        monkeypatch.setattr(voice, "synthesize", lambda text: tone(1.0))
    course = client.post(f"{URL}/courses", json={"title": "Kitchen basics"}, headers=h).json()
    lesson = add_lesson(client, h, course["id"], "Cold storage video", "video")
    return course["id"], lesson["id"]


def put_slides(client, h, lesson_id, slides):
    return client.put(f"{URL}/lessons/{lesson_id}/slides", json={"slides": slides}, headers=h)


def test_slides_are_saved_with_ids_and_pictures_and_recordings_are_kept_across_edits(client, login, monkeypatch):
    h = login(MGR)
    course_id, lesson_id = setup(client, h, monkeypatch)
    saved = put_slides(client, h, lesson_id, three_slides()).json()["slides"]
    assert [s["title"] for s in saved] == ["Cold storage basics", "Fridge rules", "Check the log"] and all(len(s["id"]) == 12 for s in saved)
    second = saved[1]["id"]
    image = client.post(f"{URL}/lessons/{lesson_id}/slides/{second}/image", files={"file": ("fridge.png", picture(), "image/png")}, headers=h)
    assert image.status_code == 201 and image.json()["slides"][1]["image"] == "fridge.png"
    voice_up = client.post(f"{URL}/lessons/{lesson_id}/slides/{saved[0]['id']}/audio", files={"file": ("intro.wav", tone(1.5), "audio/wav")}, headers=h)
    assert voice_up.json()["slides"][0]["audio"] == "intro.wav" and voice_up.json()["slides"][0]["voice"] == "upload"
    # edit the words, keep the ids: the picture and the recording stay
    current = lesson_of(client, h, course_id, lesson_id)["slides"]
    after = put_slides(client, h, lesson_id, [{**s, "title": s["title"] + "!"} for s in current]).json()["slides"]
    assert after[1]["image"] == "fridge.png" and after[0]["audio"] == "intro.wav" and after[0]["title"].endswith("!")


def test_pictures_and_recordings_are_checked(client, login, monkeypatch):
    h = login(MGR)
    _, lesson_id = setup(client, h, monkeypatch)
    sid = put_slides(client, h, lesson_id, three_slides()).json()["slides"][0]["id"]
    base = f"{URL}/lessons/{lesson_id}/slides/{sid}"
    assert client.post(f"{base}/image", files={"file": ("x.png", b"not a picture at all", "image/png")}, headers=h).status_code == 415
    assert client.post(f"{base}/image", files={"file": ("x.gif", picture(), "image/gif")}, headers=h).status_code == 415
    assert client.post(f"{base}/audio", files={"file": ("x.mp3", b"definitely not sound", "audio/mpeg")}, headers=h).status_code == 415
    assert client.post(f"{URL}/lessons/{lesson_id}/slides/nope/image", files={"file": ("x.png", picture(), "image/png")}, headers=h).status_code == 404
    assert client.post(f"{base}/image", files={"file": ("ok.png", picture(), "image/png")}, headers=h).status_code == 201
    assert client.delete(f"{base}/image", headers=h).json()["slides"][0]["image"] is None


def test_a_slide_can_be_previewed_as_a_picture(client, login, monkeypatch):
    h = login(MGR)
    _, lesson_id = setup(client, h, monkeypatch)
    slides = put_slides(client, h, lesson_id, three_slides()).json()["slides"]
    client.post(f"{URL}/lessons/{lesson_id}/slides/{slides[1]['id']}/image", files={"file": ("fridge.png", picture(), "image/png")}, headers=h)
    for slide in slides:
        shown = client.get(f"{URL}/lessons/{lesson_id}/slides/{slide['id']}/preview.png", headers=h)
        assert shown.status_code == 200 and shown.headers["content-type"] == "image/png"
        assert Image.open(io.BytesIO(shown.content)).size == (1280, 720)
    assert client.get(f"{URL}/lessons/{lesson_id}/slides/{slides[0]['id']}/preview.png", headers=login(STEWARD)).status_code == 403


def test_the_video_is_made_with_the_picture_sound_and_length_of_the_slides(client, login, monkeypatch, db):
    h = login(MGR)
    course_id, lesson_id = setup(client, h, monkeypatch)
    before = stored()
    slides = put_slides(client, h, lesson_id, three_slides()).json()["slides"]
    # the first slide gets a recorded voice-over, the third is read by the (stand-in) typed voice
    first = put_slides(client, h, lesson_id, [{**slides[0], "voice": "upload"}, *slides[1:]]).json()["slides"][0]
    client.post(f"{URL}/lessons/{lesson_id}/slides/{first['id']}/audio", files={"file": ("intro.wav", tone(2.0), "audio/wav")}, headers=h)
    started = client.post(f"{URL}/lessons/{lesson_id}/render", headers=h)
    assert started.status_code == 202 and started.json()["video"]["status"] == "queued"

    lesson = lesson_of(client, h, course_id, lesson_id)
    assert lesson["video"] == {"status": "ready", "error": None} and lesson["media"]["original"] == "Cold storage video.mp4"
    stored_file = engine.media_path(db.scalar(select(TrainingLesson.media_name).where(TrainingLesson.id == lesson_id)))
    with av.open(str(stored_file)) as video:
        kinds = {s.type: s.codec_context.name for s in video.streams}
        picture_stream = video.streams.video[0]
        assert kinds == {"video": "h264", "audio": "aac"} and (picture_stream.width, picture_stream.height) == (1280, 720)
        # slide 1: 2.0 s voice + 1.3 s breathing space; slide 2: 2 s; slide 3: 1.0 s voice + 1.3 s
        assert 7.4 < video.duration / av.time_base < 7.9
    assert db.scalar(select(AuditLog.id).where(AuditLog.action == "training.video_rendered")) is not None
    assert len(stored() - before) == 2  # the finished video and the recording; nothing left over from making it
    assert engine.signature_ok(".mp4", stored_file.read_bytes()[:64])


def test_the_made_video_can_be_watched_and_published_like_any_uploaded_one(client, login, monkeypatch):
    h = login(MGR)
    course_id, lesson_id = setup(client, h, monkeypatch)
    assert client.put(f"{URL}/courses/{course_id}", json={"status": "published"}, headers=h).status_code == 400
    put_slides(client, h, lesson_id, three_slides()[:2])
    blocked = client.put(f"{URL}/courses/{course_id}", json={"status": "published"}, headers=h)
    assert blocked.status_code == 400 and "has slides but its video has not been made yet" in blocked.json()["detail"]
    client.post(f"{URL}/lessons/{lesson_id}/render", headers=h)
    assert client.put(f"{URL}/courses/{course_id}", json={"status": "published"}, headers=h).status_code == 200
    link = client.get(f"{URL}/lessons/{lesson_id}/media-url", headers=h).json()
    assert link["type"] == "video/mp4" and link["inline"] is True
    part = client.get(link["url"], headers={"Range": "bytes=0-99"})
    assert part.status_code == 206 and part.content[4:8] == b"ftyp"
    assert client.get(f"{URL}/lessons/{lesson_id}/media-url", headers=login(STEWARD)).status_code == 403


def test_changing_the_slides_marks_the_video_out_of_date_and_making_it_again_replaces_it(client, login, monkeypatch, db):
    h = login(MGR)
    course_id, lesson_id = setup(client, h, monkeypatch)
    slides = put_slides(client, h, lesson_id, three_slides()[:2]).json()["slides"]
    client.post(f"{URL}/lessons/{lesson_id}/render", headers=h)
    first_file = db.scalar(select(TrainingLesson.media_name).where(TrainingLesson.id == lesson_id))
    assert engine.media_path(first_file).is_file()
    put_slides(client, h, lesson_id, [{**slides[0], "title": "A new title"}, slides[1]])
    assert lesson_of(client, h, course_id, lesson_id)["video"]["status"] == "outdated"
    client.post(f"{URL}/lessons/{lesson_id}/render", headers=h)
    db.expire_all()
    assert lesson_of(client, h, course_id, lesson_id)["video"]["status"] == "ready"
    assert not engine.media_path(first_file).exists()
    assert engine.media_path(db.scalar(select(TrainingLesson.media_name).where(TrainingLesson.id == lesson_id))).is_file()


def test_a_video_that_cannot_be_made_yet_says_why(client, login, monkeypatch):
    h = login(MGR)
    course_id, lesson_id = setup(client, h, monkeypatch, typed_voice=False)
    assert client.post(f"{URL}/lessons/{lesson_id}/render", headers=h).status_code == 400                       # no slides
    put_slides(client, h, lesson_id, [{"title": "", "voice": "none"}])
    assert "Slide 1 is empty" in client.post(f"{URL}/lessons/{lesson_id}/render", headers=h).json()["detail"]
    put_slides(client, h, lesson_id, [{"title": "Spoken", "narration": "Hello", "voice": "typed"}])
    assert "not set up on this server" in client.post(f"{URL}/lessons/{lesson_id}/render", headers=h).json()["detail"]
    assert client.get(f"{URL}/voice", headers=h).json() == {"typed": False}
    put_slides(client, h, lesson_id, [{"title": "Recorded", "voice": "upload"}])
    assert "upload the recording" in client.post(f"{URL}/lessons/{lesson_id}/render", headers=h).json()["detail"]
    text = add_lesson(client, h, course_id, "Just text", "text", body="Hi")
    assert client.put(f"{URL}/lessons/{text['id']}/slides", json={"slides": []}, headers=h).status_code == 400   # only a video lesson takes slides


def test_a_failed_render_is_reported_on_the_lesson_and_a_restart_does_not_leave_it_stuck(client, login, monkeypatch, db):
    h = login(MGR)
    course_id, lesson_id = setup(client, h, monkeypatch)
    put_slides(client, h, lesson_id, three_slides()[:1])
    before = stored()

    def broken(*_):
        raise RuntimeError("the encoder fell over")

    monkeypatch.setattr(slidevideo, "render", broken)
    assert client.post(f"{URL}/lessons/{lesson_id}/render", headers=h).status_code == 202
    assert lesson_of(client, h, course_id, lesson_id)["video"] == {"status": "failed", "error": "the encoder fell over"}
    assert stored() == before                                                                                    # nothing half-made is kept
    # a video still marked as being made when the server restarts is marked failed
    db.get(TrainingLesson, lesson_id).video_status = "rendering"
    db.commit()
    assert slidevideo.fail_interrupted(db) == 1
    db.commit()
    db.expire_all()
    assert "restarted" in lesson_of(client, h, course_id, lesson_id)["video"]["error"]
    db.get(TrainingLesson, lesson_id).video_status = "rendering"
    db.commit()
    assert put_slides(client, h, lesson_id, three_slides()[:1]).status_code == 409                                # not while it is being made
    assert client.post(f"{URL}/lessons/{lesson_id}/render", headers=h).status_code == 409


def test_deleting_a_lesson_takes_its_pictures_recordings_and_video_with_it(client, login, monkeypatch):
    h = login(MGR)
    _, lesson_id = setup(client, h, monkeypatch)
    before = stored()
    slides = put_slides(client, h, lesson_id, three_slides()[:2]).json()["slides"]
    client.post(f"{URL}/lessons/{lesson_id}/slides/{slides[0]['id']}/image", files={"file": ("a.png", picture(), "image/png")}, headers=h)
    put_slides(client, h, lesson_id, [slides[0], {**slides[1], "voice": "upload"}])
    client.post(f"{URL}/lessons/{lesson_id}/slides/{slides[1]['id']}/audio", files={"file": ("b.wav", tone(1.0), "audio/wav")}, headers=h)
    client.post(f"{URL}/lessons/{lesson_id}/render", headers=h)
    assert len(stored() - before) == 3
    assert client.delete(f"{URL}/lessons/{lesson_id}", headers=h).status_code == 200
    assert stored() == before


def test_the_recording_is_really_heard_in_the_video_on_its_own_slide_and_only_there(client, login, monkeypatch, db):
    """Not just that an audio track exists: the sound in it is the recording, where the slide's voice-over is, and silence elsewhere."""
    import numpy as np

    h = login(MGR)
    _, lesson_id = setup(client, h, monkeypatch)
    slides = put_slides(client, h, lesson_id, [{"title": "Silent", "voice": "none", "seconds": 3}, {"title": "Spoken", "voice": "upload", "seconds": 3}]).json()["slides"]
    client.post(f"{URL}/lessons/{lesson_id}/slides/{slides[1]['id']}/audio", files={"file": ("voice.wav", tone(2.0), "audio/wav")}, headers=h)
    client.post(f"{URL}/lessons/{lesson_id}/render", headers=h)
    stored_file = engine.media_path(db.scalar(select(TrainingLesson.media_name).where(TrainingLesson.id == lesson_id)))
    with av.open(str(stored_file)) as video:
        sound = np.concatenate([frame.to_ndarray().astype(np.float32) for frame in video.decode(audio=0)], axis=1)
    loudness = lambda start, end: float(np.sqrt((sound[:, int(start * 44100):int(end * 44100)] ** 2).mean()))
    assert loudness(0.2, 2.8) < 0.001            # the first slide has no voice-over: silence
    assert loudness(3.8, 5.2) > 0.05             # the second slide: the recording, after its half-second breath
