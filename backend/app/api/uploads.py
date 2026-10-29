import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import FileResponse

from ..config import settings
from ..deps import current_user
from ..models import User

router = APIRouter(prefix="/api/uploads", tags=["uploads"])

MAX_BYTES = 5 * 1024 * 1024
NAME_RE = re.compile(r"^[0-9a-f]{32}\.(jpg|png|webp|pdf)$")


def file_kind(head: bytes) -> str | None:
    if head.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    if head.startswith(b"%PDF"):
        return "pdf"
    return None


def upload_path(name: str) -> Path:
    return Path(settings.upload_dir) / name


def is_valid_evidence(name: str | None) -> bool:
    return bool(name and NAME_RE.match(name) and upload_path(name).is_file())


@router.post("", status_code=201)
async def upload(file: UploadFile, user: User = Depends(current_user)):
    data = await file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "File exceeds 5 MB")
    kind = file_kind(data[:16])
    if not kind:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Only JPEG, PNG, WebP or PDF files are accepted")
    name = f"{uuid.uuid4().hex}.{kind}"
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    upload_path(name).write_bytes(data)
    return {"name": name}


@router.get("/{name}")
def download(name: str, user: User = Depends(current_user)):
    if not NAME_RE.match(name) or not upload_path(name).is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    return FileResponse(upload_path(name))
