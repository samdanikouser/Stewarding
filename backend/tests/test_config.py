import pytest

from app.config import Settings


@pytest.mark.parametrize("given, expected", [
    ("postgresql://user:pass@db.internal:5432/plato", "postgresql+psycopg://user:pass@db.internal:5432/plato"),
    ("postgres://user:pass@db.internal/plato", "postgresql+psycopg://user:pass@db.internal/plato"),
    ("postgresql+psycopg://user:pass@db.internal:5432/plato", "postgresql+psycopg://user:pass@db.internal:5432/plato"),
    ("sqlite:///./local.db", "sqlite:///./local.db"),
])
def test_a_hosted_postgres_url_gets_the_driver_the_app_uses(given, expected):
    assert Settings(_env_file=None, database_url=given).database_url == expected


def test_the_database_url_comes_from_the_environment_with_the_same_fix(monkeypatch):
    monkeypatch.setenv("STW_DATABASE_URL", "postgres://u:p@host:5432/db")
    assert Settings(_env_file=None).database_url == "postgresql+psycopg://u:p@host:5432/db"
