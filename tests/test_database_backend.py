from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.db.session import engine


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_test_suite_runs_against_postgresql() -> None:
    assert engine.dialect.name == "postgresql"


def test_application_config_rejects_non_postgresql_database() -> None:
    with pytest.raises(ValidationError, match="PostgreSQL"):
        Settings(database_url="unsupported://database")


def test_application_config_requires_psycopg3_driver() -> None:
    with pytest.raises(ValidationError, match="psycopg 3"):
        Settings(database_url="postgresql://supplier:secret@db:6432/supplier")


def test_default_compose_environment_supports_local_http_sessions() -> None:
    compose_source = (PROJECT_ROOT / "docker-compose.yml").read_text()
    assert "APP_ENV: ${APP_ENV:-development}" in compose_source
