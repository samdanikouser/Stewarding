from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import audit
from ..db import get_db
from ..deps import current_user
from ..models import Employee, Location, User
from ..pagination import iso
from .employees import _phone, _text

router = APIRouter(prefix="/api/profile", tags=["profile"])


class ProfileIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    phone: str | None = Field(default=None, max_length=40)
    emergency_contact: str | None = Field(default=None, max_length=200)

    _phone = field_validator("phone")(_phone)
    _contact = field_validator("emergency_contact")(_text)


def _serialize(db: Session, user: User) -> dict:
    emp = user.employee
    out = {"email": user.email, "role_label": user.role.label or user.role.name, "last_login_at": iso(user.last_login_at), "employee": None}
    if emp:
        supervisor = db.get(Employee, emp.supervisor_id) if emp.supervisor_id else None
        places = db.scalars(select(Location.name).where(Location.id.in_([el.location_id for el in emp.locations])).order_by(Location.name))
        out["employee"] = {
            "code": emp.employee_code, "full_name": emp.full_name, "job_title": emp.job_title, "company": emp.company,
            "status": emp.status, "phone": emp.phone, "emergency_contact": emp.emergency_contact,
            "date_joined": emp.date_joined.isoformat() if emp.date_joined else None,
            "supervisor": supervisor.full_name if supervisor else None, "locations": list(places)}
    return out


@router.get("")
def read_profile(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _serialize(db, user)


@router.put("")
def update_profile(body: ProfileIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Lets a person change only their own phone and emergency contact."""
    emp = user.employee
    if not emp:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This account has no employee record")
    before = {"phone": emp.phone, "emergency_contact": emp.emergency_contact}
    emp.phone = body.phone
    emp.emergency_contact = body.emergency_contact
    audit(db, user, "profile.update", "employee", emp.id, before, {"phone": emp.phone, "emergency_contact": emp.emergency_contact})
    db.commit()
    return _serialize(db, user)
