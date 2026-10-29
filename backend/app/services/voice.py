"""Typed narration read aloud by a Piper voice that runs on the server itself, with nothing sent to an outside service.

Off until `STW_TTS_VOICE` names a voice file (.onnx); see docs/DEPLOYMENT.md for choosing and installing one.
"""
import io
import threading
import wave
from pathlib import Path

from ..config import settings

_lock = threading.Lock()  # one voice, one sentence at a time
_voice = None
_loaded_from = ""


def available() -> bool:
    """Whether typed voice-over can be used: a voice file is set, exists, and the Piper package is installed."""
    if not settings.tts_voice or not Path(settings.tts_voice).is_file():
        return False
    try:
        import piper  # noqa: F401
    except ImportError:
        return False
    return True


def _load():
    global _voice, _loaded_from
    if _voice is None or _loaded_from != settings.tts_voice:
        from piper import PiperVoice

        _voice = PiperVoice.load(settings.tts_voice)
        _loaded_from = settings.tts_voice
    return _voice


def synthesize(text: str) -> bytes:
    """The text spoken aloud, as the bytes of a WAV file."""
    with _lock:
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as out:
            _load().synthesize_wav(text, out)
        return buffer.getvalue()
