from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, Time, UniqueConstraint, false, true
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from .core import ts


class ChecklistTemplate(Base):
    __tablename__ = "checklist_template"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(60))
    location_id: Mapped[int] = mapped_column(ForeignKey("location.id"), index=True)
    frequency: Mapped[str] = mapped_column(String(20))  # per_shift | daily | weekly | custom
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class ChecklistTask(Base):
    __tablename__ = "checklist_task"
    id: Mapped[int] = mapped_column(primary_key=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("checklist_template.id"), index=True)
    description: Mapped[str] = mapped_column(String(300))
    instructions: Mapped[str | None] = mapped_column(Text)
    shift_id: Mapped[int | None] = mapped_column(ForeignKey("shift.id"))
    assigned_role: Mapped[str | None] = mapped_column(String(40))
    assigned_employee_id: Mapped[int | None] = mapped_column(ForeignKey("employee.id"))
    scheduled_time: Mapped[time | None] = mapped_column(Time)
    deadline_time: Mapped[time | None] = mapped_column(Time)
    weekdays: Mapped[str] = mapped_column(String(20), default="0,1,2,3,4,5,6")  # 0 = Monday
    priority: Mapped[str] = mapped_column(String(10), default="normal")
    requires_photo: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_reading: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_verification: Mapped[bool] = mapped_column(Boolean, default=False)
    mandatory_for_checkout: Mapped[bool] = mapped_column(Boolean, default=True)
    escalation_minutes: Mapped[int | None] = mapped_column(Integer)
    active_from: Mapped[date | None] = mapped_column(Date)
    active_to: Mapped[date | None] = mapped_column(Date)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class ChecklistInstance(Base):
    __tablename__ = "checklist_instance"
    # One instance per task, local date and shift: makes scheduler generation idempotent.
    __table_args__ = (UniqueConstraint("task_id", "local_date", "shift_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("checklist_task.id"), index=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("location.id"), index=True)
    local_date: Mapped[date] = mapped_column(Date, index=True)
    shift_key: Mapped[int] = mapped_column(Integer, default=0)  # shift id, 0 when none
    status: Mapped[str] = mapped_column(String(20), default="not_started", index=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    assigned_employee_id: Mapped[int | None] = mapped_column(ForeignKey("employee.id"))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_by: Mapped[int | None] = mapped_column(ForeignKey("user.id"))
    evidence_path: Mapped[str | None] = mapped_column(String(300))
    reading: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    comment: Mapped[str | None] = mapped_column(Text)
    verified_by: Mapped[int | None] = mapped_column(ForeignKey("user.id"))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    waive_reason: Mapped[str | None] = mapped_column(Text)


class ClosedDay(Base):
    """A day (or run of days) a location is closed, or every location when none is named: its tasks and checks are not expected and send no alerts."""

    __tablename__ = "closed_day"
    id: Mapped[int] = mapped_column(primary_key=True)
    location_id: Mapped[int | None] = mapped_column(ForeignKey("location.id"), index=True)
    start_date: Mapped[date] = mapped_column(Date, index=True)
    end_date: Mapped[date] = mapped_column(Date)
    reason: Mapped[str] = mapped_column(String(200))
    created_by: Mapped[int] = mapped_column(ForeignKey("user.id"))
    created_at: Mapped[datetime] = ts()


class TaskAssignment(Base):
    __tablename__ = "task_assignment"
    id: Mapped[int] = mapped_column(primary_key=True)
    instance_id: Mapped[int] = mapped_column(ForeignKey("checklist_instance.id"), index=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employee.id"), index=True)
    assigned_by: Mapped[int] = mapped_column(ForeignKey("user.id"))
    created_at: Mapped[datetime] = ts()


class TaskCompletion(Base):
    __tablename__ = "task_completion"
    id: Mapped[int] = mapped_column(primary_key=True)
    instance_id: Mapped[int] = mapped_column(ForeignKey("checklist_instance.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    status: Mapped[str] = mapped_column(String(20))
    comment: Mapped[str | None] = mapped_column(Text)
    evidence_path: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = ts()


class Equipment(Base):
    __tablename__ = "equipment"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(40))  # monitoring type from the managed list
    location_id: Mapped[int] = mapped_column(ForeignKey("location.id"), index=True)
    manufacturer: Mapped[str | None] = mapped_column(String(80))
    model: Mapped[str | None] = mapped_column(String(80))
    serial_number: Mapped[str | None] = mapped_column(String(80))
    supervisor_id: Mapped[int | None] = mapped_column(ForeignKey("employee.id"))
    status: Mapped[str] = mapped_column(String(20), default="operational")
    procedure_reference: Mapped[str | None] = mapped_column(String(300))
    maintenance_notes: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class EquipmentSchedule(Base):
    """One check on a monitoring point: what is measured, its limits and how often it is due."""

    __tablename__ = "equipment_schedule"
    id: Mapped[int] = mapped_column(primary_key=True)
    equipment_id: Mapped[int] = mapped_column(ForeignKey("equipment.id"), index=True)
    stage: Mapped[str] = mapped_column(String(60))  # check name, e.g. Wash, Core temperature
    parameter: Mapped[str] = mapped_column(String(60), default="Temperature")
    unit: Mapped[str | None] = mapped_column(String(20))
    value_type: Mapped[str] = mapped_column(String(10), default="number")  # number | yes_no | text | choice
    options: Mapped[list | None] = mapped_column(JSON)  # the answers a choice field offers
    fail_options: Mapped[list | None] = mapped_column(JSON)  # the choices that count as a failure
    max_length: Mapped[int | None] = mapped_column(Integer)  # longest written answer
    require_reference: Mapped[bool] = mapped_column(Boolean, default=False)  # batch, lot or product reference
    trace_lots: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())  # the check must name the food lots it used
    required: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())  # an optional question may be left blank
    reference_label: Mapped[str | None] = mapped_column(String(40))  # what the reference is called, e.g. Item name
    phase: Mapped[str | None] = mapped_column(String(10))  # start or finish of a two-step log; empty for a single entry
    source: Mapped[str] = mapped_column(String(20), default="machine_display")  # or independent_probe
    timing: Mapped[str] = mapped_column(String(20))  # startup | interval | checkpoint
    weekdays: Mapped[str | None] = mapped_column(String(20))  # "0,2,4" Monday-based; empty means every day
    day_of_month: Mapped[int | None] = mapped_column(Integer)  # monthly checks
    time_of_day: Mapped[time | None] = mapped_column(Time)
    interval_minutes: Mapped[int | None] = mapped_column(Integer)
    shift_id: Mapped[int | None] = mapped_column(ForeignKey("shift.id"))
    min_value: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    max_value: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class TemperatureReading(Base):
    __tablename__ = "temperature_reading"
    id: Mapped[int] = mapped_column(primary_key=True)
    equipment_id: Mapped[int] = mapped_column(ForeignKey("equipment.id"), index=True)
    schedule_id: Mapped[int | None] = mapped_column(ForeignKey("equipment_schedule.id"))
    location_id: Mapped[int] = mapped_column(ForeignKey("location.id"), index=True)
    recorded_at: Mapped[datetime] = ts(index=True)
    stage: Mapped[str] = mapped_column(String(60))
    source: Mapped[str] = mapped_column(String(20))
    parameter: Mapped[str] = mapped_column(String(60), default="Temperature")  # snapshot at time of reading
    unit: Mapped[str | None] = mapped_column(String(20))
    value_type: Mapped[str] = mapped_column(String(10), default="number")
    value: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))  # a yes/no answer is stored as 1 or 0; none for text and choice
    answer: Mapped[str | None] = mapped_column(String(500))  # the written or chosen answer
    reference: Mapped[str | None] = mapped_column(String(120))
    min_limit: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    max_limit: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    passed: Mapped[bool] = mapped_column(Boolean)
    recorded_by: Mapped[int] = mapped_column(ForeignKey("user.id"))
    comment: Mapped[str | None] = mapped_column(Text)
    evidence_path: Mapped[str | None] = mapped_column(String(300))
    retest_of_id: Mapped[int | None] = mapped_column(ForeignKey("temperature_reading.id"))
    start_reading_id: Mapped[int | None] = mapped_column(ForeignKey("temperature_reading.id"), index=True)  # the time-in reading a finish closes
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("user.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    rejected_by: Mapped[int | None] = mapped_column(ForeignKey("user.id"))  # a rejected reading must be recorded again
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime)
    reject_reason: Mapped[str | None] = mapped_column(String(300))


class CorrectiveAction(Base):
    __tablename__ = "corrective_action"
    id: Mapped[int] = mapped_column(primary_key=True)
    reading_id: Mapped[int] = mapped_column(ForeignKey("temperature_reading.id"), index=True)
    action: Mapped[str] = mapped_column(Text)
    taken_by: Mapped[int] = mapped_column(ForeignKey("user.id"))
    taken_at: Mapped[datetime] = ts()
    retest_due_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime)
