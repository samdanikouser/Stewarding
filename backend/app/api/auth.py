import time
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit import audit
from ..db import get_db
from ..deps import current_user, permissions_of, scoped_locations
from ..models import Employee, Location, Role, User
from ..permissions import MODULES, STEWARD
from ..security import check_password_rules, create_token, hash_password, verify_password
from .. import timeutil
from ..services.settings import get_setting
from .employees import next_code

router = APIRouter(prefix="/api/auth", tags=["auth"])

MAX_FAILURES = 5
WINDOW_SECONDS = 900
_failures: dict[str, list[float]] = defaultdict(list)
# verifying against this keeps unknown-email and wrong-password timing alike
_DUMMY_HASH = hash_password("not-a-real-password")


class LoginIn(BaseModel):
    email: str
    password: str


class SignupIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    email: str = Field(max_length=200, pattern=r"^[^@\s]+@[^@\s]+$")
    password: str = Field(max_length=128)


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10, max_length=128)


def _recent_failures(email: str) -> list[float]:
    cutoff = time.monotonic() - WINDOW_SECONDS
    _failures[email] = [t for t in _failures[email] if t > cutoff]
    return _failures[email]


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    if len(_recent_failures(email)) >= MAX_FAILURES:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts, try again later")
    user = db.scalar(select(User).where(User.email == email))
    ok = verify_password(body.password, user.password_hash if user else _DUMMY_HASH)
    if user and ok and user.employee and user.employee.status == "pending":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Your account is waiting for a manager to approve it")
    inactive = bool(user and (not user.active or (user.employee and user.employee.status != "active")))
    if not user or not ok or inactive:
        _failures[email].append(time.monotonic())
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    _failures.pop(email, None)
    user.last_login_at = timeutil.utc_now()
    audit(db, user, "login", "user", user.id)
    db.commit()
    return {"access_token": create_token(user.id, user.token_version), "token_type": "bearer",
            "change_required": user.must_change_password}


@router.post("/signup", status_code=status.HTTP_202_ACCEPTED)
def signup(body: SignupIn, request: Request, db: Session = Depends(get_db)):
    """Requests a Steward account that stays pending until a manager approves it in Employees."""
    key = f"signup:{request.client.host if request.client else ''}"
    if len(_recent_failures(key)) >= MAX_FAILURES:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts, try again later")
    _failures[key].append(time.monotonic())
    email = body.email.strip().lower()
    try:
        check_password_rules(body.password, email)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    done = {"detail": "Request sent. You can sign in once a manager approves it."}
    if db.scalar(select(User.id).where(User.email == email)):
        return done
    try:
        account = User(email=email, password_hash=hash_password(body.password), active=False,
                       role_id=db.scalar(select(Role.id).where(Role.name == STEWARD)))
        db.add(account)
        db.flush()
        employee = Employee(employee_code=next_code(db), user_id=account.id, full_name=body.full_name.strip(),
                            job_title="Steward", email=email, status="pending")
        db.add(employee)
        db.flush()
    except IntegrityError:
        db.rollback()
        return done
    audit(db, account, "signup", "employee", employee.id)
    db.commit()
    return done


@router.post("/change-password")
def change_password(body: ChangePasswordIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Sets a new password for the signed-in user and ends every older session, returning a fresh token."""
    key = f"password:{user.id}"
    if len(_recent_failures(key)) >= MAX_FAILURES:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts, try again later")
    if not verify_password(body.current_password, user.password_hash):
        _failures[key].append(time.monotonic())
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The current password is not correct")
    if body.new_password == body.current_password:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Choose a password you have not used just now")
    try:
        check_password_rules(body.new_password, user.email)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    _failures.pop(key, None)
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    user.token_version += 1
    audit(db, user, "password.change", "user", user.id)
    db.commit()
    return {"access_token": create_token(user.id, user.token_version), "token_type": "bearer"}


@router.post("/sign-out-others")
def sign_out_others(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Ends every other session of the signed-in user and returns a fresh token for this one."""
    user.token_version += 1
    audit(db, user, "session.sign_out_others", "user", user.id)
    db.commit()
    return {"access_token": create_token(user.id, user.token_version), "token_type": "bearer"}


@router.get("/me")
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    perms = permissions_of(user)
    allowed = scoped_locations(user, db)
    query = select(Location).where(Location.active.is_(True))
    if allowed is not None:
        query = query.where(Location.id.in_(allowed))
    return {
        "by_location": bool(get_setting(db, "attendance.by_location")),
        "id": user.id,
        "email": user.email,
        "change_required": user.must_change_password,
        "role": user.role.name,
        "role_label": user.role.label or user.role.name,
        "tier": user.role.tier,
        "employee": {"id": user.employee.id, "name": user.employee.full_name, "code": user.employee.employee_code}
        if user.employee
        else None,
        "permissions": sorted(perms),
        "locations": [{"id": loc.id, "code": loc.code, "name": loc.name, "timezone": loc.timezone,
                       "geofence": bool(loc.geofence_radius_m)}
                      for loc in db.scalars(query.order_by(Location.name))],
        "modules": [{"key": k, "label": label} for k, label, perm in MODULES if perm in perms],
    }
