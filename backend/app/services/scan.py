import hashlib
import hmac
from datetime import timedelta

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import timeutil
from ..config import settings
from ..models import ScanEvent, User
from .settings import get_setting

KINDS = {"equipment": "e", "location": "l"}


def _signature(kind: str, target_id: int) -> str:
    return hmac.new(settings.secret_key.encode(), f"scan:{kind}:{target_id}".encode(), hashlib.sha256).hexdigest()[:20]


def make_token(kind: str, target_id: int) -> str:
    return f"{KINDS[kind]}{target_id}.{_signature(kind, target_id)}"


def read_token(token: str) -> tuple[str, int] | None:
    """The kind and id a genuine code names, or None when the code is not one of ours."""
    head, _, signature = token.strip().partition(".")
    kind = next((k for k, letter in KINDS.items() if head[:1] == letter), None)
    if kind is None or not head[1:].isdigit():
        return None
    target_id = int(head[1:])
    return (kind, target_id) if hmac.compare_digest(signature, _signature(kind, target_id)) else None


def require_scan(db: Session, user: User, kind: str, target_id: int, setting: str, name: str) -> None:
    """403 when scanning is required for this kind of record and the user has not scanned this place recently."""
    if not get_setting(db, setting):
        return
    since = timeutil.utc_now() - timedelta(minutes=get_setting(db, "scan.valid_minutes"))
    if db.scalar(select(ScanEvent.id).where(ScanEvent.user_id == user.id, ScanEvent.kind == kind,
                                            ScanEvent.target_id == target_id, ScanEvent.created_at >= since).limit(1)) is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Scan the QR code at {name} to record this")
