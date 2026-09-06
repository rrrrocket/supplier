from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


TEST_DB = Path(__file__).resolve().parent / "supplier_test.db"
for candidate in (TEST_DB, Path(f"{TEST_DB}-wal"), Path(f"{TEST_DB}-shm")):
    if candidate.exists():
        candidate.unlink()

os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"
os.environ["SESSION_SECRET"] = "test-session-secret-with-more-than-thirty-two-characters"
os.environ["SEED_DEMO_DATA"] = "true"
os.environ["APP_ENV"] = "testing"

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def authenticated_client(client: TestClient) -> TestClient:
    response = client.post(
        "/api/auth/login",
        json={
            "email": "supplier@matrix-one.tech",
            "password": "MatrixOne123!",
        },
    )
    assert response.status_code == 200
    return client
