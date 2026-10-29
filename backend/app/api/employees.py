import math
import re
from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator
from sqlalchemy import asc, delete, desc, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import timeutil
from ..audit import audit
from ..db import get_db
from ..deps import check_location, permissions_of, require, scoped_locations
from ..models import (AttendanceRecord, ChecklistInstance, Employee, EmployeeLocation, Location, Notification, Role, ShiftAssignment, User)
from ..pagination import iso, paginate, row
from ..services.deletion import blockers
from ..security import check_password_rules, hash_password, temporary_password

router = APIRouter(prefix="/api/employees", tags=["employees"])

RoleName = str  # any role in the role table; checked against it when saved
SORTABLE = {"full_name", "employee_code", "job_title", "status", "date_joined"}
PRIVATE = ("phone", "email", "emergency_contact", "date_joined", "weekly_schedule", "photo_path")


PHONE_RE = re.compile(r"^[0-9+()\-.\s]{5,40}$")
CODE_RE = re.compile(r"^[A-Za-z0-9._-]+$")
FIRST_DAY = date(2000, 1, 1)


def _text(value: str | None) -> str | None:
    return " ".join(value.split()) or None if isinstance(value, str) else value


def _name(value: str | None) -> str | None:
    if value is None:
        return value
    cleaned = " ".join(value.split())
    if len(cleaned) < 2:
        raise ValueError("Enter at least 2 characters")
    return cleaned


def _phone(value: str | None) -> str | None:
    value = _text(value)
    if value and not PHONE_RE.match(value):
        raise ValueError("Phone may contain digits, spaces, + ( ) - and .")
    return value


def _joined(value: date | None) -> date | None:
    if value and not (FIRST_DAY <= value <= date.today() + timedelta(days=366)):
        raise ValueError("The joining date is out of range")
    return value


class EmployeeIn(BaseModel):
    employee_code: str | None = Field(default=None, min_length=2, max_length=20, pattern=CODE_RE.pattern)  # generated when empty
    full_name: str = Field(min_length=2, max_length=120)
    job_title: str = Field(min_length=2, max_length=80)
    company: str | None = Field(default=None, max_length=120)
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    role: RoleName
    phone: str | None = Field(default=None, max_length=40)
    emergency_contact: str | None = Field(default=None, max_length=200)
    date_joined: date | None = None
    supervisor_id: int | None = None
    location_ids: list[int] = Field(default_factory=list)  # none chosen: not tied to an outlet, so every location
    weekly_schedule: dict | None = None

    _names = field_validator("full_name", "job_title")(_name)
    _phone = field_validator("phone")(_phone)
    _contact = field_validator("emergency_contact", "company")(_text)
    _joined = field_validator("date_joined")(_joined)

    @model_validator(mode="after")
    def _password_rules(self):
        check_password_rules(self.password, str(self.email))
        return self


class ResetPasswordIn(BaseModel):
    new_password: str | None = Field(default=None, min_length=10, max_length=128)


class EmployeeUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=120)
    email: EmailStr | None = None
    job_title: str | None = Field(default=None, min_length=2, max_length=80)
    company: str | None = Field(default=None, max_length=120)
    role: RoleName | None = None
    phone: str | None = Field(default=None, max_length=40)
    emergency_contact: str | None = Field(default=None, max_length=200)
    date_joined: date | None = None
    supervisor_id: int | None = None
    location_ids: list[int] | None = None
    weekly_schedule: dict | None = None

    _names = field_validator("full_name", "job_title")(_name)
    _phone = field_validator("phone")(_phone)
    _contact = field_validator("emergency_contact", "company")(_text)
    _joined = field_validator("date_joined")(_joined)


def _location_ids(emp: Employee) -> list[int]:
    return sorted(el.location_id for el in emp.locations)


def serialize(emp: Employee, full: bool) -> dict:
    out = row(emp, "id", "employee_code", "full_name", "job_title", "company", "status", "supervisor_id")
    out["face_enrolled"] = emp.face_descriptor is not None
    out["location_ids"] = _location_ids(emp)
    out["role"] = emp.user.role.name if emp.user else None
    out["role_label"] = (emp.user.role.label or emp.user.role.name) if emp.user else None
    out["role_tier"] = emp.user.role.tier if emp.user else None
    if full:
        out.update(row(emp, *PRIVATE))
        out["account"] = ({"change_required": emp.user.must_change_password, "last_login_at": iso(emp.user.last_login_at)}
                          if emp.user else None)
    return out


def _snapshot(emp: Employee) -> dict:
    return {"full_name": emp.full_name, "job_title": emp.job_title, "supervisor_id": emp.supervisor_id,
            "location_ids": _location_ids(emp), "role": emp.user.role.name if emp.user else None}


def _get_visible(db: Session, user: User, employee_id: int) -> Employee:
    emp = db.get(Employee, employee_id)
    if not emp:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Employee not found")
    allowed = scoped_locations(user, db)
    if allowed is not None and emp.locations and not (set(_location_ids(emp)) & allowed):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Employee is outside your locations")
    return emp


def _validate_refs(db: Session, location_ids: list[int], supervisor_id: int | None) -> None:
    found = set(db.scalars(select(Location.id).where(Location.id.in_(location_ids))))
    if found != set(location_ids):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown location")
    if supervisor_id is not None and not db.get(Employee, supervisor_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown supervisor")


@router.get("")
def list_employees(
    search: str | None = None, status_: str | None = Query(None, alias="status"), location_id: int | None = None,
    sort: str = "full_name", direction: Literal["asc", "desc"] = Query("asc", alias="dir"),
    page: int = 1, size: int = 25,
    user: User = Depends(require("employee.view")), db: Session = Depends(get_db),
):
    stmt = select(Employee)
    allowed = scoped_locations(user, db)
    if location_id is not None:
        check_location(user, db, location_id)
    if allowed is not None or location_id is not None:
        subq = select(EmployeeLocation.employee_id)
        if allowed is not None:
            subq = subq.where(EmployeeLocation.location_id.in_(allowed))
        if location_id is not None:
            subq = subq.where(EmployeeLocation.location_id == location_id)
        stmt = stmt.where(or_(Employee.id.in_(subq), Employee.id.not_in(select(EmployeeLocation.employee_id))))  # no outlet = everywhere
    if search:
        like = f"%{search.strip()}%"
        stmt = stmt.where(or_(Employee.full_name.ilike(like), Employee.employee_code.ilike(like), Employee.company.ilike(like)))
    if status_:
        stmt = stmt.where(Employee.status == status_)
    column = getattr(Employee, sort if sort in SORTABLE else "full_name")
    stmt = stmt.order_by(asc(column) if direction == "asc" else desc(column), Employee.id)
    total, rows = paginate(db, stmt, page, size)
    full = user.role.tier == "manager"
    return {"total": total, "page": page, "items": [serialize(r[0], full) for r in rows]}


def _assignable_role(db: Session, actor: User, name: str) -> Role:
    """The named role, unless it does not exist or would give more than the person assigning it holds."""
    role = db.scalar(select(Role).where(Role.name == name))
    if role is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown role")
    if actor.role.tier != "manager" and (role.tier == "manager" or not {p.permission for p in role.permissions} <= permissions_of(actor)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You cannot assign a role with more access than your own")
    return role


def next_code(db: Session) -> str:
    """E followed by the next number after the highest existing E-number, such as E007."""
    numbers = [int(code[1:]) for code in db.scalars(select(Employee.employee_code).where(Employee.employee_code.like("E%"))) if code[1:].isdigit()]
    return f"E{max(numbers, default=0) + 1:03d}"


@router.post("", status_code=201)
def create_employee(body: EmployeeIn, user: User = Depends(require("employee.manage")), db: Session = Depends(get_db)):
    location_ids = body.location_ids
    _validate_refs(db, location_ids, body.supervisor_id)
    role = _assignable_role(db, user, body.role)
    try:
        account = User(email=str(body.email).lower(), password_hash=hash_password(body.password), role_id=role.id,
                       must_change_password=True)
        db.add(account)
        db.flush()
        emp = Employee(
            employee_code=body.employee_code or next_code(db), user_id=account.id, full_name=body.full_name, job_title=body.job_title, company=body.company,
            email=str(body.email).lower(), phone=body.phone, emergency_contact=body.emergency_contact,
            date_joined=body.date_joined, supervisor_id=body.supervisor_id, weekly_schedule=body.weekly_schedule)
        emp.locations = [EmployeeLocation(location_id=i) for i in set(location_ids)]
        db.add(emp)
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Employee code or email already exists") from None
    db.refresh(emp)
    audit(db, user, "employee.create", "employee", emp.id, None, _snapshot(emp))
    db.commit()
    return serialize(emp, True)


@router.get("/{employee_id}")
def get_employee(employee_id: int, user: User = Depends(require("employee.view")), db: Session = Depends(get_db)):
    emp = _get_visible(db, user, employee_id)
    return serialize(emp, user.role.tier == "manager")


@router.put("/{employee_id}")
def update_employee(employee_id: int, body: EmployeeUpdate, user: User = Depends(require("employee.manage")),
                    db: Session = Depends(get_db)):
    emp = db.get(Employee, employee_id)
    if not emp:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Employee not found")
    data = body.model_dump(exclude_unset=True)
    _validate_refs(db, data.get("location_ids") or _location_ids(emp), data.get("supervisor_id"))
    before = _snapshot(emp)
    if "location_ids" in data:
        wanted = set(data.pop("location_ids"))
        emp.locations = [el for el in emp.locations if el.location_id in wanted] + [
            EmployeeLocation(employee_id=emp.id, location_id=i) for i in wanted - set(_location_ids(emp))]
    if "role" in data:
        new_role = _assignable_role(db, user, data.pop("role"))
        if emp.user and emp.user.role_id != new_role.id:
            if emp.user_id == user.id:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot change your own role")
            emp.user.role_id = new_role.id
    if "email" in data:
        email = str(data.pop("email")).lower()
        clash = db.scalar(select(User.id).where(User.email == email, User.id != (emp.user_id or 0)))
        if clash or db.scalar(select(Employee.id).where(Employee.email == email, Employee.id != emp.id)):
            raise HTTPException(status.HTTP_409_CONFLICT, "That email is already used by another employee")
        emp.email = email
        if emp.user:
            emp.user.email = email
    for key, value in data.items():
        setattr(emp, key, value)
    db.flush()
    db.refresh(emp)
    after = _snapshot(emp)
    audit(db, user, "employee.update", "employee", emp.id, before, after)
    if (before["location_ids"], before["supervisor_id"]) != (after["location_ids"], after["supervisor_id"]):
        audit(db, user, "employee.assignment_change", "employee", emp.id,
              {k: before[k] for k in ("location_ids", "supervisor_id")},
              {k: after[k] for k in ("location_ids", "supervisor_id")})
    db.commit()
    return serialize(emp, True)


def _set_active(db: Session, user: User, employee_id: int, active: bool) -> dict:
    emp = db.get(Employee, employee_id)
    if not emp:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Employee not found")
    if emp.user_id == user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot change your own account status")
    before = emp.status
    emp.status = "active" if active else "inactive"
    if emp.user:
        emp.user.active = active
    audit(db, user, "employee.activate" if active else "employee.deactivate", "employee", emp.id,
          {"status": before}, {"status": emp.status})
    db.commit()
    return serialize(emp, True)


@router.post("/{employee_id}/reset-password")
def reset_password(employee_id: int, body: ResetPasswordIn, user: User = Depends(require("employee.manage")),
                   db: Session = Depends(get_db)):
    """Sets a temporary password the employee must replace at their next sign-in, and ends their open sessions."""
    emp = db.get(Employee, employee_id)
    if not emp or not emp.user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Employee not found")
    if emp.user_id == user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Use Change password for your own account")
    password = body.new_password or temporary_password()
    try:
        check_password_rules(password, emp.user.email)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    emp.user.password_hash = hash_password(password)
    emp.user.must_change_password = True
    emp.user.token_version += 1
    audit(db, user, "password.reset", "employee", emp.id, None, {"employee_id": emp.id})
    db.commit()
    return {"temporary_password": password, "change_required": True}


class FaceIn(BaseModel):
    descriptor: list[float] = Field(min_length=128, max_length=128)


@router.post("/{employee_id}/face")
def enroll_face(employee_id: int, body: FaceIn, user: User = Depends(require("employee.manage")), db: Session = Depends(get_db)):
    """Stores the face template of an employee (128 numbers, never a photo) for check-in verification."""
    emp = _get_visible(db, user, employee_id)
    if not all(math.isfinite(v) and abs(v) < 10 for v in body.descriptor):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The face template is not valid")
    emp.face_descriptor, emp.face_enrolled_at = body.descriptor, timeutil.utc_now()
    audit(db, user, "employee.face_enroll", "employee", emp.id, None, None)
    db.commit()
    return serialize(emp, True)


@router.delete("/{employee_id}/face")
def remove_face(employee_id: int, user: User = Depends(require("employee.manage")), db: Session = Depends(get_db)):
    emp = _get_visible(db, user, employee_id)
    emp.face_descriptor = emp.face_enrolled_at = None
    audit(db, user, "employee.face_remove", "employee", emp.id, None, None)
    db.commit()
    return serialize(emp, True)


@router.post("/{employee_id}/deactivate")
def deactivate(employee_id: int, user: User = Depends(require("employee.manage")), db: Session = Depends(get_db)):
    return _set_active(db, user, employee_id, False)


@router.post("/{employee_id}/activate")
def activate(employee_id: int, user: User = Depends(require("employee.manage")), db: Session = Depends(get_db)):
    return _set_active(db, user, employee_id, True)


@router.get("/{employee_id}/history")
def history(employee_id: int, user: User = Depends(require("attendance.view")), db: Session = Depends(get_db)):
    emp = _get_visible(db, user, employee_id)
    records = db.scalars(select(AttendanceRecord).where(AttendanceRecord.employee_id == emp.id)
                         .order_by(AttendanceRecord.check_in_at.desc()).limit(30))
    tasks = db.execute(
        select(ChecklistInstance.status).where(ChecklistInstance.completed_by == emp.user_id)).scalars().all()
    return {
        "attendance": [row(r, "id", "location_id", "local_date", "check_in_at", "check_out_at", "late_minutes",
                           "payable_minutes", "overtime_minutes") for r in records],
        "tasks_completed": len(tasks),
    }


@router.delete("/{employee_id}")
def delete_employee(employee_id: int, user: User = Depends(require("employee.manage")), db: Session = Depends(get_db)):
    """Removes an employee added by mistake with their roster entries and alerts; anyone with real history is refused and should be deactivated instead."""
    emp = _get_visible(db, user, employee_id)
    if emp.user_id == user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot delete your own account")
    account = emp.user
    used = blockers(db, emp, frozenset({"employee_location", "shift_assignment"})) + (blockers(db, account, frozenset({"employee", "notification"})) if account else [])
    if used:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{emp.full_name} is used by {', '.join(dict.fromkeys(used))}; deactivate them instead")
    before = {"employee_code": emp.employee_code, "full_name": emp.full_name, "email": emp.email}
    db.execute(delete(EmployeeLocation).where(EmployeeLocation.employee_id == emp.id))
    db.execute(delete(ShiftAssignment).where(ShiftAssignment.employee_id == emp.id))
    db.delete(emp)
    db.flush()
    if account:
        db.execute(delete(Notification).where(Notification.user_id == account.id))
        db.delete(account)
    audit(db, user, "employee.delete", "employee", employee_id, before, None)
    db.commit()
    return {"deleted": employee_id}
