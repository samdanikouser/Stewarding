from datetime import date, time, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from .. import timeutil
from ..audit import audit
from ..db import get_db
from ..deps import check_location, permissions_of, require, role_names, scoped_locations
from ..models import (ChecklistInstance, ChecklistTask, ChecklistTemplate, Employee, EmployeeLocation, Location,
                      Shift, TaskAssignment, TaskCompletion, User)
from ..pagination import paginate, row
from ..permissions import MANAGER, STEWARD, SUPERVISOR
from ..services import checklists as engine
from ..services.checklists import DONE, OPEN, effective_status, overdue_after
from ..services.notify import notify, recipients
from ..services.scan import require_scan
from ..services.settings import get_setting
from ..services.starter import apply_starter
from .uploads import is_valid_evidence

router = APIRouter(prefix="/api/checklists", tags=["checklists"])

FREQUENCIES = ("per_shift", "daily", "weekly", "custom")
TASK_FIELDS = ("id", "template_id", "description", "instructions", "shift_id", "assigned_role",
               "assigned_employee_id", "scheduled_time", "deadline_time", "weekdays", "priority", "requires_photo",
               "requires_reading", "requires_verification", "mandatory_for_checkout", "escalation_minutes",
               "active_from", "active_to", "active")


class TemplateIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    category: str = Field(min_length=2, max_length=60)
    location_id: int
    frequency: str = Field(pattern="^(per_shift|daily|weekly|custom)$")


class TemplateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    category: str | None = None
    frequency: str | None = Field(default=None, pattern="^(per_shift|daily|weekly|custom)$")
    active: bool | None = None


class TaskIn(BaseModel):
    description: str = Field(min_length=3, max_length=300)
    instructions: str | None = None
    shift_id: int | None = None
    assigned_role: str | None = Field(default=None, pattern="^(steward|supervisor|manager)$")
    assigned_employee_id: int | None = None
    scheduled_time: time | None = None
    deadline_time: time | None = None
    weekdays: str = Field(default="0,1,2,3,4,5,6", pattern=r"^[0-6](,[0-6])*$")
    priority: str = Field(default="normal", pattern="^(low|normal|high|critical)$")
    requires_photo: bool = False
    requires_reading: bool = False
    requires_verification: bool = False
    mandatory_for_checkout: bool = True
    escalation_minutes: int | None = Field(default=None, ge=0)
    active_from: date | None = None
    active_to: date | None = None
    active: bool = True

    @model_validator(mode="after")
    def _times_and_dates(self):
        if self.active_from and self.active_to and self.active_to < self.active_from:
            raise ValueError("The task cannot end before it starts")
        if self.shift_id is None and self.scheduled_time and self.deadline_time and self.deadline_time <= self.scheduled_time:
            raise ValueError("The deadline must be later than the scheduled time")
        return self


class CompleteIn(BaseModel):
    comment: str | None = Field(default=None, max_length=1000)
    reading: Decimal | None = None
    evidence_path: str | None = None


class VerifyIn(BaseModel):
    approve: bool
    comment: str | None = Field(default=None, max_length=1000)


class WaiveIn(BaseModel):
    reason: str = Field(min_length=5, max_length=500)


class AssignIn(BaseModel):
    employee_id: int


class GenerateIn(BaseModel):
    location_id: int


def _template_or_404(db: Session, template_id: int) -> ChecklistTemplate:
    template = db.get(ChecklistTemplate, template_id)
    if not template:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found")
    return template


@router.get("/templates")
def list_templates(location_id: int | None = None, user: User = Depends(require("checklist.view")),
                   db: Session = Depends(get_db)):
    stmt = select(ChecklistTemplate)
    allowed = scoped_locations(user, db)
    if location_id is not None:
        check_location(user, db, location_id)
        stmt = stmt.where(ChecklistTemplate.location_id == location_id)
    elif allowed is not None:
        stmt = stmt.where(ChecklistTemplate.location_id.in_(allowed))
    out = []
    for t in db.scalars(stmt.order_by(ChecklistTemplate.location_id, ChecklistTemplate.name)):
        tasks = db.scalars(select(ChecklistTask).where(ChecklistTask.template_id == t.id).order_by(ChecklistTask.id))
        out.append({**row(t, "id", "name", "category", "location_id", "frequency", "active"),
                    "tasks": [row(k, *TASK_FIELDS) for k in tasks]})
    return out


@router.post("/templates", status_code=201)
def create_template(body: TemplateIn, user: User = Depends(require("checklist.configure")),
                    db: Session = Depends(get_db)):
    check_location(user, db, body.location_id)
    _ensure_unique_name(db, body.location_id, body.name)
    template = ChecklistTemplate(**body.model_dump())
    db.add(template)
    db.flush()
    audit(db, user, "checklist.template_create", "checklist_template", template.id, None, body.model_dump())
    db.commit()
    return row(template, "id", "name", "category", "location_id", "frequency", "active")


@router.put("/templates/{template_id}")
def update_template(template_id: int, body: TemplateUpdate, user: User = Depends(require("checklist.configure")),
                    db: Session = Depends(get_db)):
    template = _template_or_404(db, template_id)
    data = body.model_dump(exclude_unset=True)
    if data.get("name"):
        _ensure_unique_name(db, template.location_id, data["name"], template.id)
    before = {k: getattr(template, k) for k in data}
    for key, value in data.items():
        setattr(template, key, value)
    audit(db, user, "checklist.template_update", "checklist_template", template.id, before, data)
    db.commit()
    return row(template, "id", "name", "category", "location_id", "frequency", "active")


def _ensure_unique_name(db: Session, location_id: int, name: str, own_id: int | None = None) -> None:
    clash = select(ChecklistTemplate.id).where(ChecklistTemplate.location_id == location_id,
                                               func.lower(ChecklistTemplate.name) == " ".join(name.split()).lower())
    if own_id is not None:
        clash = clash.where(ChecklistTemplate.id != own_id)
    if db.scalar(clash):
        raise HTTPException(status.HTTP_409_CONFLICT, "A checklist with this name already exists at this location")


def _check_task_refs(db: Session, body: "TaskIn") -> None:
    if body.shift_id is not None and not db.get(Shift, body.shift_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown shift")
    if body.assigned_employee_id is not None and not db.get(Employee, body.assigned_employee_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown employee")


@router.post("/templates/{template_id}/tasks", status_code=201)
def create_task(template_id: int, body: TaskIn, user: User = Depends(require("checklist.configure")),
                db: Session = Depends(get_db)):
    template = _template_or_404(db, template_id)
    _check_task_refs(db, body)
    task = ChecklistTask(template_id=template.id, **body.model_dump())
    db.add(task)
    db.flush()
    audit(db, user, "checklist.task_create", "checklist_task", task.id, None, body.model_dump(mode="json"))
    db.commit()
    return row(task, *TASK_FIELDS)


@router.put("/tasks/{task_id}")
def update_task(task_id: int, body: TaskIn, user: User = Depends(require("checklist.configure")),
                db: Session = Depends(get_db)):
    task = db.get(ChecklistTask, task_id)
    if not task:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    _check_task_refs(db, body)
    before = row(task, *TASK_FIELDS)
    for key, value in body.model_dump().items():
        setattr(task, key, value)
    audit(db, user, "checklist.task_update", "checklist_task", task.id,
          {k: str(v) for k, v in before.items()}, body.model_dump(mode="json"))
    db.commit()
    return row(task, *TASK_FIELDS)


@router.delete("/tasks/{task_id}")
def deactivate_task(task_id: int, user: User = Depends(require("checklist.configure")), db: Session = Depends(get_db)):
    task = db.get(ChecklistTask, task_id)
    if not task:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    task.active = False
    audit(db, user, "checklist.task_deactivate", "checklist_task", task.id, {"active": True}, {"active": False})
    db.commit()
    return {"ok": True}


@router.post("/starter", status_code=201)
def starter_templates(body: GenerateIn, user: User = Depends(require("checklist.configure")),
                      db: Session = Depends(get_db)):
    check_location(user, db, body.location_id)
    added = apply_starter(db, body.location_id)
    audit(db, user, "checklist.starter_applied", "location", body.location_id, None, {"tasks_added": added})
    db.commit()
    return {"tasks_added": added}


@router.post("/generate")
def generate_now(body: GenerateIn, user: User = Depends(require("checklist.configure")), db: Session = Depends(get_db)):
    check_location(user, db, body.location_id)
    created = engine.generate_for_location(db, db.get(Location, body.location_id), timeutil.utc_now())
    db.commit()
    return {"created": created}


def _serialize(inst: ChecklistInstance, task: ChecklistTask, template: ChecklistTemplate, now) -> dict:
    out = row(inst, "id", "task_id", "location_id", "local_date", "shift_key", "status", "due_at",
              "assigned_employee_id", "completed_at", "completed_by", "evidence_path", "reading", "comment",
              "verified_by", "verified_at", "waive_reason")
    out["effective_status"] = effective_status(inst, now)
    out.update({"description": task.description, "instructions": task.instructions, "priority": task.priority,
                "requires_photo": task.requires_photo, "requires_reading": task.requires_reading,
                "requires_verification": task.requires_verification, "category": template.category,
                "frequency": template.frequency, "template_name": template.name})
    return out


def _base_stmt():
    return (select(ChecklistInstance, ChecklistTask, ChecklistTemplate)
            .join(ChecklistTask, ChecklistTask.id == ChecklistInstance.task_id)
            .join(ChecklistTemplate, ChecklistTemplate.id == ChecklistTask.template_id))


def _steward_filter(user: User):
    emp_id = user.employee.id if user.employee else -1
    return and_(or_(ChecklistInstance.assigned_employee_id == emp_id, ChecklistInstance.assigned_employee_id.is_(None)),
                or_(ChecklistTask.assigned_role.is_(None), ChecklistTask.assigned_role.in_(role_names(user))))


@router.get("/instances")
def list_instances(location_id: int | None = None, day: date | None = None, date_from: date | None = None,
                   date_to: date | None = None, frequency: str | None = None,
                   status_: str | None = Query(None, alias="status"), mine: bool = False, page: int = 1, size: int = 50,
                   user: User = Depends(require("checklist.view")), db: Session = Depends(get_db)):
    now = timeutil.utc_now()
    stmt = _base_stmt()
    allowed = scoped_locations(user, db)
    if location_id is not None:
        check_location(user, db, location_id)
        stmt = stmt.where(ChecklistInstance.location_id == location_id)
    elif allowed is not None:
        stmt = stmt.where(ChecklistInstance.location_id.in_(allowed))
    if day:
        stmt = stmt.where(ChecklistInstance.local_date == day)
    if date_from:
        stmt = stmt.where(ChecklistInstance.local_date >= date_from)
    if date_to:
        stmt = stmt.where(ChecklistInstance.local_date <= date_to)
    if frequency:
        stmt = stmt.where(ChecklistTemplate.frequency == frequency)
    is_late = and_(ChecklistInstance.status.in_(OPEN), ChecklistInstance.due_at < overdue_after(db, now))
    if status_ == "overdue":
        stmt = stmt.where(or_(ChecklistInstance.status == "overdue", is_late))
    elif status_ in OPEN:
        stmt = stmt.where(ChecklistInstance.status == status_, ~is_late)
    elif status_:
        stmt = stmt.where(ChecklistInstance.status == status_)
    if user.role.tier == STEWARD:
        stmt = stmt.where(_steward_filter(user))
    if mine and user.employee:
        stmt = stmt.where(ChecklistInstance.assigned_employee_id == user.employee.id)
    stmt = stmt.order_by(ChecklistInstance.local_date.desc(), ChecklistInstance.due_at, ChecklistInstance.id)
    total, rows = paginate(db, stmt, page, size)
    late_now = overdue_after(db, now)
    return {"total": total, "items": [_serialize(i, t, tpl, late_now) for i, t, tpl in rows]}


def _load(db: Session, user: User, instance_id: int):
    found = db.execute(_base_stmt().where(ChecklistInstance.id == instance_id)).first()
    if not found:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    inst, task, template = found
    check_location(user, db, inst.location_id)
    if user.role.tier == STEWARD:
        mine = inst.assigned_employee_id in (None, user.employee.id if user.employee else -1)
        if not (mine and (task.assigned_role is None or task.assigned_role in role_names(user))):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "This task is assigned to someone else")
    return inst, task, template


@router.get("/instances/{instance_id}")
def get_instance(instance_id: int, user: User = Depends(require("checklist.view")), db: Session = Depends(get_db)):
    inst, task, template = _load(db, user, instance_id)
    return _serialize(inst, task, template, overdue_after(db))


@router.post("/instances/{instance_id}/start")
def start(instance_id: int, user: User = Depends(require("checklist.complete")), db: Session = Depends(get_db)):
    inst, task, template = _load(db, user, instance_id)
    if inst.status not in ("not_started", "failed"):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Task is {inst.status}")
    inst.status = "in_progress"
    db.commit()
    return _serialize(inst, task, template, overdue_after(db))


@router.post("/instances/{instance_id}/complete")
def complete(instance_id: int, body: CompleteIn, user: User = Depends(require("checklist.complete")),
             db: Session = Depends(get_db)):
    inst, task, template = _load(db, user, instance_id)
    if inst.status in ("completed", "pending_verification", "verified", "waived"):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Task is already {inst.status}")
    now = timeutil.utc_now()
    location = db.get(Location, inst.location_id)
    require_scan(db, user, "location", location.id, "scan.checklists_required", location.name)
    if inst.local_date > timeutil.local_date(now, location.timezone):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This task is scheduled for a future date")
    if task.requires_reading and body.reading is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A numeric reading is required")
    if task.requires_photo and not is_valid_evidence(body.evidence_path):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Photo evidence is required")
    if body.evidence_path and not is_valid_evidence(body.evidence_path):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown evidence file")
    needs_approval = task.requires_verification or get_setting(db, "approval.checklists") == 1
    inst.status = "pending_verification" if needs_approval else "completed"
    inst.completed_at = now
    inst.completed_by = user.id
    inst.reading, inst.comment, inst.evidence_path = body.reading, body.comment, body.evidence_path
    db.add(TaskCompletion(instance_id=inst.id, user_id=user.id, status=inst.status, comment=body.comment,
                          evidence_path=body.evidence_path))
    if inst.status == "pending_verification":
        notify(db, recipients(db, inst.location_id, SUPERVISOR, MANAGER), "verification_needed",
               f"Verify: {task.description}", key=f"verify:{inst.id}", location_id=inst.location_id,
               link="/checklists", priority="high")
    db.commit()
    return _serialize(inst, task, template, overdue_after(db, now))


@router.post("/instances/{instance_id}/verify")
def verify(instance_id: int, body: VerifyIn, user: User = Depends(require("checklist.verify")),
           db: Session = Depends(get_db)):
    inst, task, template = _load(db, user, instance_id)
    if inst.status != "pending_verification":
        raise HTTPException(status.HTTP_409_CONFLICT, "Task is not awaiting verification")
    if inst.completed_by == user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You cannot verify your own work")
    if not body.approve and not (body.comment and body.comment.strip()):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A comment is required when rejecting")
    now = timeutil.utc_now()
    inst.status = "verified" if body.approve else "failed"
    inst.verified_by, inst.verified_at = user.id, now
    if body.comment:
        inst.comment = f"{inst.comment}\nVerifier: {body.comment}" if inst.comment else f"Verifier: {body.comment}"
    audit(db, user, "checklist.verify" if body.approve else "checklist.reject", "checklist_instance", inst.id,
          {"status": "pending_verification"}, {"status": inst.status})
    if not body.approve and inst.completed_by:
        notify(db, [inst.completed_by], "task_rejected", f"Redo: {task.description}",
               key=f"reject:{inst.id}:{now.isoformat()}", location_id=inst.location_id, priority="high")
    db.commit()
    return _serialize(inst, task, template, overdue_after(db, now))


class VerifyManyIn(BaseModel):
    instance_ids: list[int] = Field(min_length=1, max_length=200)


@router.post("/instances/verify-many")
def verify_many(body: VerifyManyIn, user: User = Depends(require("checklist.verify")), db: Session = Depends(get_db)):
    """Approves every chosen task that awaits verification; your own work and tasks in other states are skipped."""
    now, approved = timeutil.utc_now(), []
    for inst in db.scalars(select(ChecklistInstance).where(ChecklistInstance.id.in_(set(body.instance_ids)))):
        check_location(user, db, inst.location_id)
        if inst.status != "pending_verification" or inst.completed_by == user.id:
            continue
        inst.status, inst.verified_by, inst.verified_at = "verified", user.id, now
        approved.append(inst.id)
    audit(db, user, "checklist.verify_many", "checklist_instance", None, None, {"instance_ids": sorted(approved)})
    db.commit()
    return {"approved": len(approved), "skipped": len(set(body.instance_ids)) - len(approved)}


class AssignManyIn(VerifyManyIn):
    employee_id: int


class WaiveManyIn(VerifyManyIn):
    reason: str = Field(min_length=5, max_length=500)


def _many(db: Session, user: User, ids: list[int]) -> list[ChecklistInstance]:
    found = list(db.scalars(select(ChecklistInstance).where(ChecklistInstance.id.in_(set(ids)))))
    for inst in found:
        check_location(user, db, inst.location_id)
    return found


@router.post("/instances/assign-many")
def assign_many(body: AssignManyIn, user: User = Depends(require("task.assign")), db: Session = Depends(get_db)):
    """Gives the chosen unfinished tasks to one employee; tasks at a location they do not work at, or already finished, are skipped."""
    emp = db.get(Employee, body.employee_id)
    if not emp or emp.status != "active":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Employee is not active")
    places = set(db.scalars(select(EmployeeLocation.location_id).where(EmployeeLocation.employee_id == emp.id)))
    now, given = timeutil.utc_now(), []
    for inst in _many(db, user, body.instance_ids):
        if inst.location_id not in places or inst.status in DONE:
            continue
        db.add(TaskAssignment(instance_id=inst.id, employee_id=emp.id, assigned_by=user.id))
        inst.assigned_employee_id = emp.id
        given.append(inst.id)
    audit(db, user, "task.assign_many", "checklist_instance", None, None, {"employee_id": emp.id, "instance_ids": sorted(given)})
    if given and emp.user_id:
        notify(db, [emp.user_id], "task_assigned", f"{len(given)} task{'s' if len(given) != 1 else ''} assigned to you",
               key=f"assign-many:{emp.id}:{now.isoformat()}", priority="normal", link="/checklists")
    db.commit()
    return {"assigned": len(given), "skipped": len(set(body.instance_ids)) - len(given)}


@router.post("/instances/waive-many")
def waive_many(body: WaiveManyIn, user: User = Depends(require("checklist.verify")), db: Session = Depends(get_db)):
    """Waives the chosen tasks with one reason; tasks already verified or waived are skipped."""
    now, waived = timeutil.utc_now(), []
    for inst in _many(db, user, body.instance_ids):
        if inst.status in ("verified", "waived"):
            continue
        inst.status, inst.waive_reason, inst.verified_by, inst.verified_at = "waived", body.reason, user.id, now
        waived.append(inst.id)
    audit(db, user, "checklist.waive_many", "checklist_instance", None, None, {"reason": body.reason, "instance_ids": sorted(waived)})
    db.commit()
    return {"waived": len(waived), "skipped": len(set(body.instance_ids)) - len(waived)}


@router.post("/instances/{instance_id}/waive")
def waive(instance_id: int, body: WaiveIn, user: User = Depends(require("checklist.verify")),
          db: Session = Depends(get_db)):
    inst, task, template = _load(db, user, instance_id)
    if inst.status in ("verified", "waived"):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Task is already {inst.status}")
    before = inst.status
    inst.status, inst.waive_reason = "waived", body.reason
    inst.verified_by, inst.verified_at = user.id, timeutil.utc_now()
    audit(db, user, "checklist.waive", "checklist_instance", inst.id, {"status": before},
          {"status": "waived", "reason": body.reason})
    db.commit()
    return _serialize(inst, task, template, overdue_after(db))


@router.post("/instances/{instance_id}/assign")
def assign(instance_id: int, body: AssignIn, user: User = Depends(require("task.assign")),
           db: Session = Depends(get_db)):
    inst, task, template = _load(db, user, instance_id)
    emp = db.get(Employee, body.employee_id)
    works_here = emp and db.scalar(select(EmployeeLocation.employee_id).where(
        EmployeeLocation.employee_id == emp.id, EmployeeLocation.location_id == inst.location_id))
    if not works_here or emp.status != "active":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Employee is not active at this location")
    if inst.status in DONE:
        raise HTTPException(status.HTTP_409_CONFLICT, "Task is already finished")
    before = inst.assigned_employee_id
    inst.assigned_employee_id = emp.id
    db.add(TaskAssignment(instance_id=inst.id, employee_id=emp.id, assigned_by=user.id))
    audit(db, user, "task.assign", "checklist_instance", inst.id, {"employee_id": before}, {"employee_id": emp.id})
    if emp.user_id:
        notify(db, [emp.user_id], "task_assigned", f"New task: {task.description}",
               key=f"assign:{inst.id}:{emp.id}", location_id=inst.location_id, due_at=inst.due_at)
    db.commit()
    return _serialize(inst, task, template, overdue_after(db))


DELETE_GRACE_DAYS = 3  # a checklist made in error is noticed within days; older untouched tasks are missed work and stay on record


def _grace_start(db: Session, location_id: int) -> date:
    return timeutil.local_date(timeutil.utc_now(), db.get(Location, location_id).timezone) - timedelta(days=DELETE_GRACE_DAYS)


@router.delete("/templates/{template_id}")
def delete_template(template_id: int, user: User = Depends(require("checklist.configure")), db: Session = Depends(get_db)):
    """Deletes a checklist and its tasks when nothing was ever recorded against them."""
    template = _template_or_404(db, template_id)
    check_location(user, db, template.location_id)
    tasks = list(db.scalars(select(ChecklistTask).where(ChecklistTask.template_id == template.id)))
    if not engine.drop_untouched_instances(db, [t.id for t in tasks], _grace_start(db, template.location_id)):
        raise HTTPException(status.HTTP_409_CONFLICT, f"{template.name} has records of work done; make it inactive instead")
    before = {"name": template.name, "category": template.category, "frequency": template.frequency, "tasks": len(tasks)}
    for task in tasks:
        db.delete(task)
    db.flush()
    db.delete(template)
    audit(db, user, "checklist.template_delete", "checklist_template", template_id, before, None)
    db.commit()
    return {"deleted": template_id}


@router.post("/tasks/{task_id}/remove")
def remove_task(task_id: int, user: User = Depends(require("checklist.configure")), db: Session = Depends(get_db)):
    """Deletes a task nothing was recorded against; one with records should be made inactive instead."""
    task = db.get(ChecklistTask, task_id)
    if not task:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    location_id = _template_or_404(db, task.template_id).location_id
    check_location(user, db, location_id)
    if not engine.drop_untouched_instances(db, [task.id], _grace_start(db, location_id)):
        raise HTTPException(status.HTTP_409_CONFLICT, "This task has records of work done; make it inactive instead")
    before = row(task, *TASK_FIELDS)
    db.delete(task)
    audit(db, user, "checklist.task_delete", "checklist_task", task_id, {k: str(v) for k, v in before.items()}, None)
    db.commit()
    return {"deleted": task_id}
