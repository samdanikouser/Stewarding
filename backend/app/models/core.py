from datetime import date, datetime, time, timezone

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, Time, UniqueConstraint, false, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base


def utcnow() -> datetime:
    """Naive UTC; every DateTime column in the schema stores UTC."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def ts(**kw):
    return mapped_column(DateTime, default=utcnow, **kw)


class Role(Base):
    __tablename__ = "role"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(40), unique=True)
    label: Mapped[str | None] = mapped_column(String(80))  # what people see; the name is the stable key
    tier: Mapped[str] = mapped_column(String(20), default="steward", server_default="steward")  # manager | supervisor | steward behaviour
    builtin: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    permissions: Mapped[list["RolePermission"]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class RolePermission(Base):
    __tablename__ = "role_permission"
    role_id: Mapped[int] = mapped_column(ForeignKey("role.id"), primary_key=True)
    permission: Mapped[str] = mapped_column(String(60), primary_key=True)


class Location(Base):
    __tablename__ = "location"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(30))
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    latitude: Mapped[float | None] = mapped_column(Float)  # centre of the area check-in and check-out are limited to
    longitude: Mapped[float | None] = mapped_column(Float)
    geofence_radius_m: Mapped[int | None] = mapped_column(Integer)  # empty means no restriction


class User(Base):
    __tablename__ = "user"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(200), unique=True)
    password_hash: Mapped[str] = mapped_column(String(100))
    role_id: Mapped[int] = mapped_column(ForeignKey("role.id"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = ts()
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    token_version: Mapped[int] = mapped_column(Integer, default=0)  # raising it signs out every older session
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)
    role: Mapped[Role] = relationship(lazy="joined")
    employee: Mapped["Employee | None"] = relationship(back_populates="user", lazy="joined")


class Employee(Base):
    __tablename__ = "employee"
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_code: Mapped[str] = mapped_column(String(20), unique=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"), unique=True)
    full_name: Mapped[str] = mapped_column(String(120), index=True)
    phone: Mapped[str | None] = mapped_column(String(40))
    email: Mapped[str | None] = mapped_column(String(200))
    job_title: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), default="active")
    supervisor_id: Mapped[int | None] = mapped_column(ForeignKey("employee.id"))
    date_joined: Mapped[date | None] = mapped_column(Date)
    emergency_contact: Mapped[str | None] = mapped_column(String(200))
    company: Mapped[str | None] = mapped_column(String(120))  # organization or contractor the employee works for
    face_descriptor: Mapped[list | None] = mapped_column(JSON)  # 128 numbers from the face model; never a photo
    face_enrolled_at: Mapped[datetime | None] = mapped_column(DateTime)
    photo_path: Mapped[str | None] = mapped_column(String(300))
    weekly_schedule: Mapped[dict | None] = mapped_column(JSON)
    user: Mapped[User | None] = relationship(back_populates="employee")
    locations: Mapped[list["EmployeeLocation"]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class EmployeeLocation(Base):
    __tablename__ = "employee_location"
    employee_id: Mapped[int] = mapped_column(ForeignKey("employee.id"), primary_key=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("location.id"), primary_key=True)


class Shift(Base):
    __tablename__ = "shift"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60))
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    kind: Mapped[str] = mapped_column(String(10), default="work")  # work | weekoff
    grace_minutes: Mapped[int] = mapped_column(Integer, default=10)
    break_minutes: Mapped[int] = mapped_column(Integer, default=0)
    overtime_after_minutes: Mapped[int | None] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


CYCLE_EPOCH = date(2020, 1, 6)  # a Monday: the first week of every roster cycle


class ShiftAssignment(Base):
    __tablename__ = "shift_assignment"
    __table_args__ = (UniqueConstraint("employee_id", "shift_id", "location_id", "weekday", "valid_from"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employee.id"), index=True)
    shift_id: Mapped[int] = mapped_column(ForeignKey("shift.id"))
    location_id: Mapped[int] = mapped_column(ForeignKey("location.id"), index=True)
    weekday: Mapped[int] = mapped_column(Integer)
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    cycle_weeks: Mapped[int] = mapped_column(Integer, default=1, server_default="1")  # 1 = every week, 2 = alternate weeks
    cycle_week: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # which week of the cycle, counted from CYCLE_EPOCH

    def applies_on(self, day: date) -> bool:
        """Whether this weekly assignment falls on `day`: the weekday, the dates it is valid for and the week of its cycle."""
        return (self.weekday == day.weekday() and self.valid_from <= day and (self.valid_to is None or self.valid_to >= day)
                and ((day - CYCLE_EPOCH).days // 7) % self.cycle_weeks == self.cycle_week)


class AttendanceRecord(Base):
    __tablename__ = "attendance_record"
    # open_flag is 1 while checked in and NULL once closed; NULLs are distinct, so this
    # allows only one open record per employee on SQLite and PostgreSQL.
    __table_args__ = (UniqueConstraint("employee_id", "open_flag", name="uq_one_open_attendance"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employee.id"), index=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("location.id"), index=True)
    shift_id: Mapped[int | None] = mapped_column(ForeignKey("shift.id"))
    local_date: Mapped[date] = mapped_column(Date, index=True)
    check_in_at: Mapped[datetime] = ts()
    check_out_at: Mapped[datetime | None] = mapped_column(DateTime)
    open_flag: Mapped[int | None] = mapped_column(Integer)
    late_minutes: Mapped[int] = mapped_column(Integer, default=0)
    payable_minutes: Mapped[int | None] = mapped_column(Integer)
    overtime_minutes: Mapped[int | None] = mapped_column(Integer)
    exception_reason: Mapped[str | None] = mapped_column(Text)
    verified_by: Mapped[int | None] = mapped_column(ForeignKey("user.id"))
    check_in_geo: Mapped[dict | None] = mapped_column(JSON)  # latitude, longitude, accuracy, distance and flags at check-in
    check_out_geo: Mapped[dict | None] = mapped_column(JSON)
    check_in_face: Mapped[float | None] = mapped_column(Float)  # distance from the enrolled face at check-in
    check_out_face: Mapped[float | None] = mapped_column(Float)
    check_in_snapshot: Mapped[str | None] = mapped_column(String(60))  # file name in the faces folder, taken at the live check
    check_out_snapshot: Mapped[str | None] = mapped_column(String(60))

    @property
    def geo_flags(self) -> list[str]:
        return [f for geo in (self.check_in_geo, self.check_out_geo) if geo for f in geo["flags"]]


class FaceChallenge(Base):
    """A one-use sequence of head turns the camera screen must show before a face check is accepted."""

    __tablename__ = "face_challenge"
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employee.id"), index=True)
    token: Mapped[str] = mapped_column(String(64), unique=True)
    action: Mapped[str] = mapped_column(String(3))  # in | out
    steps: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = ts(index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime)


class AttendanceCorrection(Base):
    __tablename__ = "attendance_correction"
    id: Mapped[int] = mapped_column(primary_key=True)
    attendance_id: Mapped[int] = mapped_column(ForeignKey("attendance_record.id"), index=True)
    corrected_by: Mapped[int] = mapped_column(ForeignKey("user.id"))
    field: Mapped[str] = mapped_column(String(40))
    old_value: Mapped[str | None] = mapped_column(String(80))
    new_value: Mapped[str | None] = mapped_column(String(80))
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = ts()


class Setting(Base):
    __tablename__ = "setting"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)


class AbsenceRecord(Base):
    """A recorded absence or leave day for one employee; voided rows stay for the history."""

    __tablename__ = "absence_record"
    # one live record per employee and day; a voided one frees the day for correct re-entry
    __table_args__ = (Index("uq_absence_employee_day", "employee_id", "local_date", unique=True,
                            sqlite_where=text("voided_at IS NULL"), postgresql_where=text("voided_at IS NULL")),)
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employee.id"), index=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("location.id"), index=True)
    local_date: Mapped[date] = mapped_column(Date, index=True)
    absence_type: Mapped[str] = mapped_column(String(20))  # absent | day_off | sick_leave | annual_leave | unpaid_leave | other_leave
    note: Mapped[str | None] = mapped_column(Text)
    recorded_by: Mapped[int] = mapped_column(ForeignKey("user.id"))
    created_at: Mapped[datetime] = ts()
    voided_by: Mapped[int | None] = mapped_column(ForeignKey("user.id"))
    voided_at: Mapped[datetime | None] = mapped_column(DateTime)
    void_reason: Mapped[str | None] = mapped_column(Text)
