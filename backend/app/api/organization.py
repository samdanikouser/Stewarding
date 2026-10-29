import re
import uuid
from pathlib import Path
from zoneinfo import ZoneInfo, available_timezones

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from ..audit import audit
from ..config import settings
from ..db import get_db
from ..deps import current_user, require
from ..models import Organization, User
from ..services.organization import get_organization, logo_file

router = APIRouter(prefix="/api/organization", tags=["organization"])

LOGO_BYTES = 2 * 1024 * 1024
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _image_kind(head: bytes) -> str | None:
    if head.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    return None


class OrganizationIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    legal_name: str | None = Field(default=None, max_length=160)
    address: str | None = Field(default=None, max_length=500)
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=120)
    website: str | None = Field(default=None, max_length=200)
    registration_number: str | None = Field(default=None, max_length=60)
    report_footer: str | None = Field(default=None, max_length=300)
    timezone: str = Field(default="Asia/Kuwait", max_length=64)
    currency: str | None = Field(default=None, max_length=8)

    @field_validator("currency")
    @classmethod
    def _currency(cls, value):
        value = (value or "").strip().upper()
        if value and not re.match(r"^[A-Z$€£]{1,8}$", value):
            raise ValueError("Use the currency letters or symbol, for example KWD")
        return value or None

    @field_validator("timezone")
    @classmethod
    def _timezone(cls, value):
        try:
            ZoneInfo(value)
        except Exception:
            raise ValueError("Choose a time zone from the list, for example Asia/Kuwait") from None
        return value

    @field_validator("legal_name", "address", "phone", "email", "website", "registration_number", "report_footer")
    @classmethod
    def _strip(cls, value):
        return value.strip() or None if isinstance(value, str) else value

    @field_validator("name")
    @classmethod
    def _name(cls, value):
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Enter the organization name")
        return value

    @field_validator("email")
    @classmethod
    def _email(cls, value):
        if value and not EMAIL_RE.match(value):
            raise ValueError("Enter a valid email address")
        return value

    @field_validator("phone")
    @classmethod
    def _phone(cls, value):
        if value and not re.match(r"^[0-9+()\-.\s]{5,40}$", value):
            raise ValueError("Phone may contain digits, spaces, + ( ) - and .")
        return value

    @field_validator("website")
    @classmethod
    def _website(cls, value):
        if value and not re.match(r"^https?://\S+$", value):
            raise ValueError("The website must start with http:// or https://")
        return value


@router.get("")
def read_organization(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return get_organization(db)


@router.get("/timezones")
def timezones(user: User = Depends(current_user)):
    return sorted(available_timezones())


@router.get("/public")
def public_identity(db: Session = Depends(get_db)):
    """The name and whether a logo exists, for the sign-in page."""
    org = get_organization(db)
    return {"name": org["name"], "has_logo": logo_file(db) is not None}


@router.get("/logo")
def logo(db: Session = Depends(get_db)):
    path = logo_file(db)
    if not path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No logo")
    return FileResponse(path, headers={"Cache-Control": "no-cache"})


@router.put("")
def update_organization(body: OrganizationIn, user: User = Depends(require("settings.manage")), db: Session = Depends(get_db)):
    org = db.get(Organization, 1)
    before = get_organization(db)
    if not org:
        org = Organization(id=1)
        db.add(org)
    for key, value in body.model_dump().items():
        setattr(org, key, value)
    db.flush()
    audit(db, user, "organization.update", "organization", 1, {k: v for k, v in before.items() if k != "logo"}, body.model_dump())
    db.commit()
    return get_organization(db)


@router.post("/logo", status_code=201)
async def upload_logo(file: UploadFile, user: User = Depends(require("settings.manage")), db: Session = Depends(get_db)):
    data = await file.read(LOGO_BYTES + 1)
    if len(data) > LOGO_BYTES:
        raise HTTPException(413, "The logo must be under 2 MB")
    kind = _image_kind(data[:16])
    if not kind:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "The logo must be a PNG or JPEG image")
    name = f"{uuid.uuid4().hex}.{kind}"
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    (Path(settings.upload_dir) / name).write_bytes(data)
    org = db.get(Organization, 1)
    if not org:
        org = Organization(id=1)
        db.add(org)
    org.logo = name
    audit(db, user, "organization.logo", "organization", 1, None, {"logo": name})
    db.commit()
    return get_organization(db)


@router.delete("/logo")
def remove_logo(user: User = Depends(require("settings.manage")), db: Session = Depends(get_db)):
    org = db.get(Organization, 1)
    if org and org.logo:
        org.logo = None
        audit(db, user, "organization.logo", "organization", 1, None, {"logo": None})
        db.commit()
    return get_organization(db)
