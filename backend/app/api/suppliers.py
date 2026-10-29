from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import audit
from ..services.deletion import delete_if_unused
from ..db import get_db
from ..deps import require
from ..models import Supplier, User
from ..pagination import row
from ..services.inventory import norm

router = APIRouter(prefix="/api/suppliers", tags=["suppliers"])

EMAIL = r"^$|^[^@\s]+@[^@\s]+\.[^@\s]+$"
FIELDS = ("id", "name", "contact", "phone", "email", "active")


class SupplierIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    contact: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=200, pattern=EMAIL)


class SupplierUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    contact: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=200, pattern=EMAIL)
    active: bool | None = None


@router.get("")
def list_suppliers(include_inactive: bool = False, user: User = Depends(require("stock.transfer")),
                   db: Session = Depends(get_db)):
    stmt = select(Supplier).order_by(Supplier.name)
    if not include_inactive:
        stmt = stmt.where(Supplier.active.is_(True))
    return [row(s, *FIELDS) for s in db.scalars(stmt)]


@router.post("", status_code=201)
def create_supplier(body: SupplierIn, user: User = Depends(require("inventory.manage")), db: Session = Depends(get_db)):
    name = " ".join(body.name.split())
    existing = db.scalar(select(Supplier).where(Supplier.name_key == norm(name)))
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Supplier {existing.name} already exists")
    supplier = Supplier(name=name, name_key=norm(name), contact=body.contact, phone=body.phone, email=body.email)
    db.add(supplier)
    db.flush()
    audit(db, user, "supplier.create", "supplier", supplier.id, None, body.model_dump())
    db.commit()
    return row(supplier, *FIELDS)


@router.put("/{supplier_id}")
def update_supplier(supplier_id: int, body: SupplierUpdate, user: User = Depends(require("inventory.manage")),
                    db: Session = Depends(get_db)):
    supplier = db.get(Supplier, supplier_id)
    if not supplier:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Supplier not found")
    data = body.model_dump(exclude_unset=True)
    if "name" in data:
        data["name"] = " ".join(data["name"].split())
        clash = db.scalar(select(Supplier).where(Supplier.name_key == norm(data["name"]), Supplier.id != supplier.id))
        if clash:
            raise HTTPException(status.HTTP_409_CONFLICT, f"Supplier {clash.name} already exists")
    before = {k: getattr(supplier, k) for k in data}
    for key, value in data.items():
        setattr(supplier, key, value)
    if "name" in data:
        supplier.name_key = norm(data["name"])
    audit(db, user, "supplier.update", "supplier", supplier.id, before, data)
    db.commit()
    return row(supplier, *FIELDS)


@router.delete("/{supplier_id}")
def delete_supplier(supplier_id: int, user: User = Depends(require("inventory.manage")), db: Session = Depends(get_db)):
    supplier = db.get(Supplier, supplier_id)
    if not supplier:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Supplier not found")
    before = {"name": supplier.name}
    delete_if_unused(db, supplier, supplier.name)
    audit(db, user, "supplier.delete", "supplier", supplier_id, before, None)
    db.commit()
    return {"deleted": supplier_id}
