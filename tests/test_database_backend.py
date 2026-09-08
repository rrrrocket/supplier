import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.api.routes.imports import MAX_FINAL_IMPORT_REQUEST_SIZE
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


def test_nginx_upload_limit_exceeds_application_request_limit() -> None:
    nginx_source = (PROJECT_ROOT / "deploy/nginx-supplier.conf").read_text()
    match = re.search(r"client_max_body_size\s+(\d+)([kKmMgG])?;", nginx_source)
    assert match is not None

    size = int(match.group(1))
    unit = (match.group(2) or "").lower()
    multiplier = {"": 1, "k": 1024, "m": 1024**2, "g": 1024**3}[unit]
    nginx_limit = size * multiplier
    assert nginx_limit > MAX_FINAL_IMPORT_REQUEST_SIZE


def test_test_compose_uses_persistent_database_volume() -> None:
    compose_source = (PROJECT_ROOT / "docker-compose.test.yml").read_text()
    assert "tmpfs:" not in compose_source
    assert "supplier_test_postgres:/var/lib/postgresql/data" in compose_source
    assert re.search(r"(?m)^  supplier_test_postgres:\s*$", compose_source)


def test_test_command_does_not_destroy_persistent_database() -> None:
    start_source = (PROJECT_ROOT / "start.sh").read_text()
    assert "cleanup_test_environment" not in start_source
    assert "down --volumes" not in start_source
