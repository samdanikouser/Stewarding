import pytest
from sqlalchemy import select

from app.bootstrap import create_manager
from app.models import Employee, Role, User


def test_bootstrap_creates_a_working_manager_with_all_permissions(client, db):
    emp = create_manager(db, "  Owner@Example.COM ", "a-strong-password-1", "Olive Owner", "E900")
    assert emp.job_title == "Back of House Manager" and len(emp.locations) == 3
    r = client.post("/api/auth/login", json={"email": "owner@example.com", "password": "a-strong-password-1"})
    assert r.status_code == 200
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"}).json()
    assert me["role"] == "manager" and len(me["modules"]) == 18 and "checklists" in {m["key"] for m in me["modules"]} and len(me["locations"]) == 3


def test_bootstrap_rejects_weak_passwords_and_duplicates(db):
    with pytest.raises(ValueError, match="at least"):
        create_manager(db, "a@example.com", "short", "A", "E901")
    create_manager(db, "a@example.com", "a-strong-password-1", "A", "E901")
    with pytest.raises(ValueError, match="already exists"):
        create_manager(db, "a@example.com", "a-strong-password-1", "A", "E902")
    with pytest.raises(ValueError, match="already exists"):
        create_manager(db, "b@example.com", "a-strong-password-1", "B", "E901")
    assert len(db.scalars(select(User).where(User.email.in_(["a@example.com", "b@example.com"]))).all()) == 1


def test_bootstrap_on_an_empty_database_creates_the_roles(client, db):
    from app.db import Base, engine

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    db.expire_all()
    assert db.scalar(select(Role.id)) is None
    create_manager(db, "first@example.com", "a-strong-password-1", "First", "E001")
    assert {r.name for r in db.scalars(select(Role))} == {"manager", "supervisor", "steward"}
    assert db.scalar(select(Employee.id)) is not None
