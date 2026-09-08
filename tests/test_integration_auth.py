from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import psycopg
import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.integration_deps import SupplierReader
from app.core.integration_security import create_integration_token, verify_integration_token
from app.db.session import SessionLocal
from app.main import app
from app.models.entities import EventLog, IntegrationClient
from tests.conftest import ADMIN_EMAIL, ADMIN_PASSWORD, SUPPLIER_EMAIL, SUPPLIER_PASSWORD
from tests.migration_utils import connect, run_migrations, temporary_postgresql_database


PREVIOUS_REVISION = "5d91a2c74e30"
INTEGRATION_CLIENT_REVISION = "b742e6d423f0"
ALL_SCOPES = [
    "suppliers:read",
    "supplier-brands:read",
    "supplier-skus:read",
    "supplier-costs:read",
]


@app.get("/api/test/integration-supplier-reader", include_in_schema=False)
def integration_supplier_reader(principal: SupplierReader) -> dict[str, str]:
    return {"client_id": principal.id}


def login(client: TestClient, email: str, password: str) -> None:
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == status.HTTP_200_OK


def create_client(
    client: TestClient,
    *,
    name: str | None = None,
    scopes: list[str] | None = None,
    expires_at: datetime | None = None,
) -> dict[str, object]:
    login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    payload: dict[str, object] = {
        "name": name or f"测试集成方-{uuid4().hex[:8]}",
        "scopes": scopes if scopes is not None else ALL_SCOPES,
    }
    if expires_at is not None:
        payload["expires_at"] = expires_at.isoformat()
    response = client.post("/api/admin/integration-clients", json=payload)
    assert response.status_code == status.HTTP_201_CREATED
    return response.json()


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_integration_token_roundtrip_uses_prefix_and_sha256_digest() -> None:
    plaintext, prefix, digest = create_integration_token()

    assert plaintext.startswith("m1i_")
    assert len(plaintext) == 47
    assert prefix == plaintext[:12]
    assert len(prefix) == 12
    assert digest == hashlib.sha256(plaintext.encode()).hexdigest()
    assert plaintext not in digest
    assert verify_integration_token(plaintext, digest)
    assert not verify_integration_token(plaintext + "x", digest)


def test_integration_client_migration_creates_secret_safe_schema() -> None:
    with temporary_postgresql_database("integration_clients") as migration_url:
        database_name = migration_url.database
        assert database_name is not None
        run_migrations(migration_url, PREVIOUS_REVISION)
        run_migrations(migration_url, INTEGRATION_CLIENT_REVISION)

        with connect(migration_url, database_name) as connection:
            columns = dict(
                connection.execute(
                    "SELECT column_name, is_nullable FROM information_schema.columns "
                    "WHERE table_name = 'integration_clients'"
                )
            )
            assert columns == {
                "id": "NO",
                "name": "NO",
                "token_prefix": "NO",
                "token_hash": "NO",
                "scopes": "NO",
                "expires_at": "YES",
                "is_active": "NO",
                "last_used_at": "YES",
            }
            connection.execute(
                "INSERT INTO integration_clients "
                "(id, name, token_prefix, token_hash, scopes, is_active) VALUES "
                "('client-a', 'A', 'm1i_prefix-a', 'hash-a', '[]', true)"
            )
            with pytest.raises(psycopg.errors.UniqueViolation):
                connection.execute(
                    "INSERT INTO integration_clients "
                    "(id, name, token_prefix, token_hash, scopes, is_active) VALUES "
                    "('client-b', 'B', 'm1i_prefix-a', 'hash-b', '[]', true)"
                )


def test_create_and_list_never_persist_or_return_plaintext_token(client: TestClient) -> None:
    created = create_client(client)
    token = str(created["token"])
    client_id = str(created["id"])

    assert token.startswith("m1i_")
    assert created["token_prefix"] == token[:12]
    assert "token_hash" not in created

    listed_response = client.get("/api/admin/integration-clients")
    assert listed_response.status_code == status.HTTP_200_OK
    listed = next(item for item in listed_response.json() if item["id"] == client_id)
    assert listed["token_prefix"] == token[:12]
    assert "token" not in listed
    assert "token_hash" not in listed
    assert token not in listed_response.text

    with SessionLocal() as db:
        stored = db.get(IntegrationClient, client_id)
        assert stored is not None
        assert stored.token_hash == hashlib.sha256(token.encode()).hexdigest()
        assert token not in json.dumps(
            {
                "name": stored.name,
                "token_prefix": stored.token_prefix,
                "token_hash": stored.token_hash,
                "scopes": stored.scopes,
            }
        )
        events = db.scalars(
            select(EventLog).where(
                EventLog.entity_type == "IntegrationClient",
                EventLog.entity_id == client_id,
            )
        ).all()
        assert events
        assert token not in json.dumps([event.payload for event in events])


@pytest.mark.parametrize(
    ("headers", "expected_status"),
    [
        ({}, status.HTTP_401_UNAUTHORIZED),
        ({"Authorization": "Basic abc"}, status.HTTP_401_UNAUTHORIZED),
        ({"Authorization": "Bearer"}, status.HTTP_401_UNAUTHORIZED),
        ({"Authorization": "Bearer malformed token"}, status.HTTP_401_UNAUTHORIZED),
        (bearer("m1i_invalid-token"), status.HTTP_401_UNAUTHORIZED),
    ],
)
def test_missing_malformed_and_invalid_bearer_tokens_are_unauthorized(
    client: TestClient,
    headers: dict[str, str],
    expected_status: int,
) -> None:
    response = client.get("/api/test/integration-supplier-reader", headers=headers)

    assert response.status_code == expected_status


def test_expired_and_revoked_tokens_are_unauthorized(client: TestClient) -> None:
    expired_token, expired_prefix, expired_hash = create_integration_token()
    revoked_token, revoked_prefix, revoked_hash = create_integration_token()
    with SessionLocal() as db:
        db.add_all(
            [
                IntegrationClient(
                    name=f"已过期-{uuid4().hex[:8]}",
                    token_prefix=expired_prefix,
                    token_hash=expired_hash,
                    scopes=["suppliers:read"],
                    expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
                ),
                IntegrationClient(
                    name=f"已撤销-{uuid4().hex[:8]}",
                    token_prefix=revoked_prefix,
                    token_hash=revoked_hash,
                    scopes=["suppliers:read"],
                    is_active=False,
                ),
            ]
        )
        db.commit()

    for token in (expired_token, revoked_token):
        response = client.get(
            "/api/test/integration-supplier-reader",
            headers=bearer(token),
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_valid_token_without_required_scope_is_forbidden(client: TestClient) -> None:
    created = create_client(client, scopes=["supplier-brands:read"])

    response = client.get(
        "/api/test/integration-supplier-reader",
        headers=bearer(str(created["token"])),
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_successful_read_persists_last_used_at(client: TestClient) -> None:
    created = create_client(client, scopes=["suppliers:read"])
    client_id = str(created["id"])
    with SessionLocal() as db:
        stored = db.get(IntegrationClient, client_id)
        assert stored is not None
        assert stored.last_used_at is None

    response = client.get(
        "/api/test/integration-supplier-reader",
        headers=bearer(str(created["token"])),
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"client_id": client_id}
    with SessionLocal() as db:
        stored = db.get(IntegrationClient, client_id)
        assert stored is not None
        assert stored.last_used_at is not None


def test_rotate_invalidates_old_token_and_returns_new_token_once(client: TestClient) -> None:
    created = create_client(client, scopes=["suppliers:read"])
    client_id = str(created["id"])
    old_token = str(created["token"])

    rotated_response = client.post(f"/api/admin/integration-clients/{client_id}/rotate")

    assert rotated_response.status_code == status.HTTP_200_OK
    rotated = rotated_response.json()
    new_token = rotated["token"]
    assert new_token.startswith("m1i_")
    assert new_token != old_token
    assert rotated["token_prefix"] == new_token[:12]
    assert client.get(
        "/api/test/integration-supplier-reader",
        headers=bearer(old_token),
    ).status_code == status.HTTP_401_UNAUTHORIZED
    assert client.get(
        "/api/test/integration-supplier-reader",
        headers=bearer(new_token),
    ).status_code == status.HTTP_200_OK
    listed = client.get("/api/admin/integration-clients")
    assert old_token not in listed.text
    assert new_token not in listed.text


def test_revoke_immediately_invalidates_token(client: TestClient) -> None:
    created = create_client(client, scopes=["suppliers:read"])
    client_id = str(created["id"])
    token = str(created["token"])

    revoked_response = client.post(f"/api/admin/integration-clients/{client_id}/revoke")

    assert revoked_response.status_code == status.HTTP_200_OK
    assert revoked_response.json()["is_active"] is False
    assert "token" not in revoked_response.json()
    assert client.get(
        "/api/test/integration-supplier-reader",
        headers=bearer(token),
    ).status_code == status.HTTP_401_UNAUTHORIZED


def test_supplier_user_cannot_manage_integration_clients(client: TestClient) -> None:
    login(client, SUPPLIER_EMAIL, SUPPLIER_PASSWORD)

    assert client.get(
        "/api/admin/integration-clients"
    ).status_code == status.HTTP_403_FORBIDDEN
    assert client.post(
        "/api/admin/integration-clients",
        json={"name": "越权集成方", "scopes": ["suppliers:read"]},
    ).status_code == status.HTTP_403_FORBIDDEN
