from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from ..config import settings
from ..models import Organization

DEFAULT_TIMEZONE = "Asia/Kuwait"
FIELDS = ("name", "legal_name", "address", "phone", "email", "website", "registration_number", "report_footer")


def get_organization(db: Session) -> dict:
    org = db.get(Organization, 1)
    return {**{f: (getattr(org, f) if org else None) or "" for f in FIELDS}, "logo": org.logo if org else None,
            "timezone": (org.timezone if org else None) or DEFAULT_TIMEZONE, "currency": (org.currency if org else None) or ""}


def stamp(moment: datetime, tz_name: str) -> str:
    """A UTC moment as local time in the organization's zone, for the 'generated' line of a report."""
    local = moment.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(tz_name))
    return f"{local:%d %b %Y %H:%M} ({tz_name})"


def logo_file(db: Session) -> Path | None:
    org = db.get(Organization, 1)
    if not org or not org.logo:
        return None
    path = Path(settings.upload_dir) / org.logo
    return path if path.is_file() else None


def report_identity(db: Session) -> dict:
    """What the report headers need: the organization details and the logo file when there is one."""
    logo = logo_file(db)
    return {**get_organization(db), "logo_path": str(logo) if logo else None}
