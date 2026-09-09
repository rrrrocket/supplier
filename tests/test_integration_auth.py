from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import uuid4

import psycopg
import pytest
from fastapi import Depends, HTTPException, status
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.api import integration_deps
from app.api.deps import DbSession
from app.api.integration_deps import SupplierReader
from app.core.integration_security import create_integration_token, verify_integration_token
from app.core.security import hash_password
from app.db.session import SessionLocal, get_db
from app.main import app
from app.models.entities import (
    EventLog,
    IntegrationClient,
    IntegrationClientType,
    Organization,
    OrganizationType,
    User,
    UserRole,
)
from app.schemas.integration import INTEGRATION_SCOPES
from app.services import integration_clients
from tests.conftest import (
    ADMIN_EMAIL,
    ADMIN_PASSWORD,
    SUPPLIER_EMAIL,
    SUPPLIER_PASSWORD,
    TEST_DATABASE_URL,
)
from tests.migration_utils import connect, run_migrations, temporary_postgresql_database


PREVIOUS_REVISION = "5d91a2c74e30"
INTEGRATION_CLIENT_REVISION = "b742e6d423f0"
ALL_SCOPES = list(INTEGRATION_SCOPES)


@app.get("/api/test/integration-supplier-reader", include_in_schema=False)
def integration_supplier_reader(principal: SupplierReader) -> dict[str, str]:
    return {"client_id": principal.id}


@app.get("/api/test/integration-principal-snapshot", include_in_schema=False)
def integration_principal_snapshot(principal: SupplierReader) -> dict[str, object]:
    return {
        "client_id": principal.id,
        "name": principal.name,
        "scopes": principal.scopes,
    }


def stage_unrelated_supplier_change(db: DbSession) -> None:
    supplier = db.scalar(select(Organization).where(Organization.code == "TEST-SUPPLIER"))
    assert supplier is not None
    supplier.name = "THIS CHANGE MUST ROLLBACK"


StagedUnrelatedChange = Annotated[None, Depends(stage_unrelated_supplier_change)]


@app.get("/api/test/integration-scope-failure", include_in_schema=False)
def integration_scope_failure(
    _: StagedUnrelatedChange,
    __: SupplierReader,
) -> None:
    raise AssertionError("scope failure must stop before the handler")


@app.get("/api/test/integration-handler-failure", include_in_schema=False)
def integration_handler_failure(
    _: StagedUnrelatedChange,
    __: SupplierReader,
) -> None:
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="forced failure")


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


def deterministic_token(prefix: str, tail: str) -> tuple[str, str, str]:
    assert len(prefix) == 12
    plaintext = f"{prefix}{tail}"
    return plaintext, prefix, hashlib.sha256(plaintext.encode()).hexdigest()


def seed_integration_client(
    *,
    token: tuple[str, str, str],
    scopes: list[str] | None = None,
) -> str:
    _, prefix, digest = token
    with SessionLocal() as db:
        integration_client = db.scalar(
            select(IntegrationClient).where(IntegrationClient.token_prefix == prefix)
        )
        if integration_client is None:
            integration_client = IntegrationClient(
                name=f"碰撞占位-{uuid4().hex[:8]}",
                token_prefix=prefix,
                token_hash=digest,
                scopes=scopes or ["suppliers:read"],
            )
            db.add(integration_client)
        else:
            integration_client.token_hash = digest
            integration_client.scopes = scopes or ["suppliers:read"]
        db.commit()
        return integration_client.id


@contextmanager
def seeded_legacy_owned_credential(
    *,
    client_type: str,
    owner_type: str,
) -> Iterator[str]:
    plaintext, prefix, token_hash = create_integration_token()
    suffix = uuid4().hex[:8]
    credential_id = f"legacy-owned-client-{suffix}"
    with SessionLocal() as db:
        owner = Organization(
            code=f"LEGACY-OWNER-{suffix}",
            name=f"旧凭证所有者-{suffix}",
            organization_type=owner_type,
        )
        db.add(owner)
        db.commit()
        owner_id = owner.id

    try:
        with SessionLocal() as db:
            db.execute(
                text(
                    "ALTER TABLE integration_clients "
                    "DROP CONSTRAINT ck_integration_client_owner"
                )
            )
            db.add(
                IntegrationClient(
                    id=credential_id,
                    name=f"旧凭证-{suffix}",
                    client_type=client_type,
                    owner_organization_id=owner_id,
                    token_prefix=prefix,
                    token_hash=token_hash,
                    scopes=["suppliers:read"],
                )
            )
            db.commit()
        yield plaintext
    finally:
        with SessionLocal() as db:
            db.execute(
                delete(EventLog).where(
                    EventLog.entity_type == "IntegrationClient",
                    EventLog.entity_id == credential_id,
                )
            )
            db.execute(
                delete(IntegrationClient).where(IntegrationClient.id == credential_id)
            )
            db.execute(
                text(
                    "ALTER TABLE integration_clients ADD CONSTRAINT "
                    "ck_integration_client_owner CHECK ("
                    "(client_type = 'SYSTEM' AND owner_organization_id IS NULL "
                    "AND issuer_user_id IS NULL) OR "
                    "(client_type = 'SUPPLIER' AND owner_organization_id IS NOT NULL "
                    "AND issuer_user_id IS NOT NULL))"
                )
            )
            db.execute(delete(Organization).where(Organization.id == owner_id))
            db.commit()


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
    login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    created_response = client.post(
        "/api/admin/integration-clients",
        json={"name": f"测试集成方-{uuid4().hex[:8]}", "scopes": ALL_SCOPES},
    )
    assert created_response.status_code == status.HTTP_201_CREATED
    assert created_response.headers["cache-control"] == "no-store"
    created = created_response.json()
    token = str(created["token"])
    client_id = str(created["id"])

    assert token.startswith("m1i_")
    assert created["client_type"] == "SYSTEM"
    assert created["owner_organization_id"] is None
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
    assert response.headers["www-authenticate"] == "Bearer"


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


@pytest.mark.parametrize(
    ("owner_is_active", "owner_type"),
    [
        (False, OrganizationType.SUPPLIER.value),
        (True, OrganizationType.PLATFORM.value),
    ],
    ids=["inactive-owner", "non-supplier-owner"],
)
def test_supplier_token_requires_an_active_supplier_owner(
    client: TestClient,
    owner_is_active: bool,
    owner_type: str,
) -> None:
    plaintext, prefix, token_hash = create_integration_token()
    suffix = uuid4().hex[:8]
    with SessionLocal() as db:
        owner = Organization(
            code=f"INVALID-SUPPLIER-OWNER-{suffix}",
            name=f"无效凭证所有者-{suffix}",
            organization_type=owner_type,
            is_active=owner_is_active,
        )
        db.add(owner)
        db.flush()
        issuer = User(
            organization_id=owner.id,
            email=f"invalid-owner-issuer-{suffix}@example.com",
            name="无效所有者签发人",
            role=UserRole.SUPPLIER.value,
            password_hash="not-used",
        )
        db.add(issuer)
        db.flush()
        credential = IntegrationClient(
            name=f"无效供应商凭证-{suffix}",
            client_type=IntegrationClientType.SUPPLIER.value,
            owner_organization_id=owner.id,
            issuer_user_id=issuer.id,
            token_prefix=prefix,
            token_hash=token_hash,
            scopes=["suppliers:read"],
        )
        db.add(credential)
        db.commit()
        credential_id = credential.id
        owner_id = owner.id
        issuer_id = issuer.id

    try:
        response = client.get(
            "/api/test/integration-supplier-reader",
            headers=bearer(plaintext),
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.headers["www-authenticate"] == "Bearer"
    finally:
        with SessionLocal() as db:
            db.execute(
                delete(IntegrationClient).where(IntegrationClient.id == credential_id)
            )
            db.execute(delete(User).where(User.id == issuer_id))
            db.execute(delete(Organization).where(Organization.id == owner_id))
            db.commit()


@pytest.mark.parametrize(
    "invalid_issuer_state",
    ["inactive", "wrong-role", "wrong-organization"],
)
def test_supplier_token_requires_an_active_supplier_issuer_in_its_owner_organization(
    client: TestClient,
    invalid_issuer_state: str,
) -> None:
    suffix = uuid4().hex[:8]
    email = f"integration-issuer-{suffix}@example.com"
    password = "IntegrationIssuer123!"
    with SessionLocal() as db:
        owner = Organization(
            code=f"ISSUER-OWNER-{suffix}",
            name=f"签发组织-{suffix}",
            organization_type=OrganizationType.SUPPLIER.value,
            is_active=True,
        )
        other_owner = Organization(
            code=f"ISSUER-OTHER-{suffix}",
            name=f"其他签发组织-{suffix}",
            organization_type=OrganizationType.SUPPLIER.value,
            is_active=True,
        )
        db.add_all([owner, other_owner])
        db.flush()
        issuer = User(
            organization_id=owner.id,
            email=email,
            name="供应商签发人",
            role=UserRole.SUPPLIER.value,
            password_hash=hash_password(password),
            is_active=True,
        )
        db.add(issuer)
        db.commit()
        owner_id = owner.id
        other_owner_id = other_owner.id
        issuer_id = issuer.id

    login(client, email, password)
    created_response = client.post(
        "/api/supplier/integration-clients",
        json={"name": f"签发校验-{suffix}", "scopes": ["suppliers:read"]},
    )
    assert created_response.status_code == status.HTTP_201_CREATED
    created = created_response.json()
    client_id = str(created["id"])
    token = str(created["token"])

    try:
        with SessionLocal() as db:
            owner = db.get(Organization, owner_id)
            issuer = db.get(User, issuer_id)
            assert owner is not None and owner.is_active
            assert issuer is not None
            if invalid_issuer_state == "inactive":
                issuer.is_active = False
            elif invalid_issuer_state == "wrong-role":
                issuer.role = UserRole.OPERATOR.value
            else:
                issuer.organization_id = other_owner_id
            db.commit()

        response = client.get(
            "/api/test/integration-supplier-reader",
            headers=bearer(token),
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.headers["www-authenticate"] == "Bearer"
    finally:
        with SessionLocal() as db:
            db.execute(
                delete(EventLog).where(
                    EventLog.entity_type == "IntegrationClient",
                    EventLog.entity_id == client_id,
                )
            )
            db.execute(delete(IntegrationClient).where(IntegrationClient.id == client_id))
            db.execute(delete(User).where(User.id == issuer_id))
            db.execute(
                delete(Organization).where(
                    Organization.id.in_([owner_id, other_owner_id])
                )
            )
            db.commit()


def test_deleting_supplier_issuer_invalidates_its_bearer_token(
    client: TestClient,
) -> None:
    suffix = uuid4().hex[:8]
    email = f"deleted-integration-issuer-{suffix}@example.com"
    password = "DeletedIssuer123!"
    with SessionLocal() as db:
        owner = Organization(
            code=f"DELETED-ISSUER-{suffix}",
            name=f"删除签发人组织-{suffix}",
            organization_type=OrganizationType.SUPPLIER.value,
            is_active=True,
        )
        db.add(owner)
        db.flush()
        issuer = User(
            organization_id=owner.id,
            email=email,
            name="待删除签发人",
            role=UserRole.SUPPLIER.value,
            password_hash=hash_password(password),
        )
        db.add(issuer)
        db.commit()
        owner_id = owner.id
        issuer_id = issuer.id

    login(client, email, password)
    created_response = client.post(
        "/api/supplier/integration-clients",
        json={"name": f"删除签发人-{suffix}", "scopes": ["suppliers:read"]},
    )
    assert created_response.status_code == status.HTTP_201_CREATED
    created = created_response.json()
    client_id = str(created["id"])
    token = str(created["token"])

    try:
        with SessionLocal() as db:
            db.execute(delete(User).where(User.id == issuer_id))
            db.commit()

        response = client.get(
            "/api/test/integration-supplier-reader",
            headers=bearer(token),
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.headers["www-authenticate"] == "Bearer"
    finally:
        with SessionLocal() as db:
            db.execute(
                delete(EventLog).where(
                    EventLog.entity_type == "IntegrationClient",
                    EventLog.entity_id == client_id,
                )
            )
            db.execute(delete(IntegrationClient).where(IntegrationClient.id == client_id))
            db.execute(delete(Organization).where(Organization.id == owner_id))
            db.commit()


def test_legacy_operator_integration_client_cannot_authenticate(
    client: TestClient,
) -> None:
    with seeded_legacy_owned_credential(
        client_type="OPERATOR",
        owner_type=OrganizationType.OPERATOR.value,
    ) as plaintext:
        response = client.get(
            "/api/test/integration-supplier-reader",
            headers=bearer(plaintext),
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.headers["www-authenticate"] == "Bearer"


def test_system_integration_client_with_owner_cannot_authenticate(
    client: TestClient,
) -> None:
    with seeded_legacy_owned_credential(
        client_type=IntegrationClientType.SYSTEM.value,
        owner_type=OrganizationType.SUPPLIER.value,
    ) as plaintext:
        response = client.get(
            "/api/test/integration-supplier-reader",
            headers=bearer(plaintext),
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.headers["www-authenticate"] == "Bearer"


def test_valid_token_without_required_scope_is_forbidden(client: TestClient) -> None:
    created = create_client(client, scopes=["supplier-brands:read"])

    response = client.get(
        "/api/test/integration-supplier-reader",
        headers=bearer(str(created["token"])),
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.parametrize(
    ("scopes", "path", "expected_status"),
    [
        (["supplier-brands:read"], "/api/test/integration-scope-failure", 403),
        (["suppliers:read"], "/api/test/integration-handler-failure", 409),
    ],
)
def test_authentication_failure_does_not_commit_unrelated_request_changes(
    client: TestClient,
    scopes: list[str],
    path: str,
    expected_status: int,
) -> None:
    created = create_client(client, scopes=scopes)
    integration_client_id = str(created["id"])
    with SessionLocal() as db:
        supplier = db.scalar(
            select(Organization).where(Organization.code == "TEST-SUPPLIER")
        )
        assert supplier is not None
        original_name = supplier.name

    response = client.get(path, headers=bearer(str(created["token"])))

    assert response.status_code == expected_status
    with SessionLocal() as db:
        supplier = db.scalar(
            select(Organization).where(Organization.code == "TEST-SUPPLIER")
        )
        integration_client = db.get(IntegrationClient, integration_client_id)
        assert supplier is not None
        assert integration_client is not None
        persisted_name = supplier.name
        last_used_at = integration_client.last_used_at
    try:
        assert persisted_name == original_name
        assert last_used_at is not None
    finally:
        if persisted_name != original_name:
            with SessionLocal() as db:
                supplier = db.scalar(
                    select(Organization).where(Organization.code == "TEST-SUPPLIER")
                )
                assert supplier is not None
                supplier.name = original_name
                db.commit()


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


def test_authentication_uses_one_short_lived_connection_and_returns_snapshot(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = create_client(client, scopes=["suppliers:read"])
    client_id = str(created["id"])
    single_connection_engine = create_engine(
        TEST_DATABASE_URL,
        pool_size=1,
        max_overflow=0,
        pool_timeout=0.1,
    )
    SingleConnectionSession = sessionmaker(
        bind=single_connection_engine,
        autoflush=False,
        expire_on_commit=True,
    )

    def get_single_connection_db() -> Iterator[Session]:
        with SingleConnectionSession() as db:
            yield db

    app.dependency_overrides[get_db] = get_single_connection_db
    monkeypatch.setattr(integration_deps, "SessionLocal", SingleConnectionSession)
    try:
        with TestClient(app, raise_server_exceptions=False) as isolated_client:
            response = isolated_client.get(
                "/api/test/integration-principal-snapshot",
                headers=bearer(str(created["token"])),
            )
    finally:
        app.dependency_overrides.pop(get_db, None)
        single_connection_engine.dispose()

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {
        "client_id": client_id,
        "name": created["name"],
        "scopes": ["suppliers:read"],
    }
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
    assert rotated_response.headers["cache-control"] == "no-store"
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


def test_create_retries_a_token_prefix_collision(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collision = deterministic_token("m1i_COLLIDE1", "-existing")
    retry_collision = deterministic_token("m1i_COLLIDE1", "-candidate")
    unique = create_integration_token()
    seed_integration_client(token=collision)
    candidates = iter([retry_collision, unique])
    monkeypatch.setattr(
        integration_clients,
        "create_integration_token",
        lambda: next(candidates),
    )
    login(client, ADMIN_EMAIL, ADMIN_PASSWORD)

    response = client.post(
        "/api/admin/integration-clients",
        json={"name": f"碰撞重试-{uuid4().hex[:8]}", "scopes": ["suppliers:read"]},
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert response.json()["token"] == unique[0]


def test_rotate_retries_a_token_prefix_collision(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = create_client(client, scopes=["suppliers:read"])
    collision = deterministic_token("m1i_ROTATE_1", "-existing")
    retry_collision = deterministic_token("m1i_ROTATE_1", "-candidate")
    unique = create_integration_token()
    seed_integration_client(token=collision)
    candidates = iter([retry_collision, unique])
    monkeypatch.setattr(
        integration_clients,
        "create_integration_token",
        lambda: next(candidates),
    )

    response = client.post(f"/api/admin/integration-clients/{created['id']}/rotate")

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["token"] == unique[0]
    assert client.get(
        "/api/test/integration-supplier-reader",
        headers=bearer(str(created["token"])),
    ).status_code == status.HTTP_401_UNAUTHORIZED


def test_rotate_collision_exhaustion_preserves_old_token(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = create_client(client, scopes=["suppliers:read"])
    collision = deterministic_token("m1i_EXHAUST1", "-existing")
    candidate = deterministic_token("m1i_EXHAUST1", "-candidate")
    seed_integration_client(token=collision)
    attempts = 0

    def colliding_token() -> tuple[str, str, str]:
        nonlocal attempts
        attempts += 1
        return candidate

    monkeypatch.setattr(integration_clients, "create_integration_token", colliding_token)

    response = client.post(f"/api/admin/integration-clients/{created['id']}/rotate")

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert attempts == 5
    assert client.get(
        "/api/test/integration-supplier-reader",
        headers=bearer(str(created["token"])),
    ).status_code == status.HTTP_200_OK


def test_collision_retry_does_not_swallow_unrelated_integrity_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    candidate = deterministic_token("m1i_CHECK__1", "-candidate")

    def generated_token() -> tuple[str, str, str]:
        nonlocal calls
        calls += 1
        return candidate

    monkeypatch.setattr(integration_clients, "create_integration_token", generated_token)
    with SessionLocal() as db:
        db.execute(
            text(
                "ALTER TABLE integration_clients ADD CONSTRAINT "
                "ck_integration_clients_review_forced_error "
                "CHECK (name <> 'FORCED UNRELATED INTEGRITY ERROR')"
            )
        )
        db.commit()
    try:
        with TestClient(app, raise_server_exceptions=False) as retry_client:
            login(retry_client, ADMIN_EMAIL, ADMIN_PASSWORD)
            response = retry_client.post(
                "/api/admin/integration-clients",
                json={
                    "name": "FORCED UNRELATED INTEGRITY ERROR",
                    "scopes": ["suppliers:read"],
                },
            )
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert calls == 1
    finally:
        with SessionLocal() as db:
            db.execute(
                text(
                    "ALTER TABLE integration_clients DROP CONSTRAINT "
                    "ck_integration_clients_review_forced_error"
                )
            )
            db.commit()


def test_create_rejects_naive_expiration_datetime(client: TestClient) -> None:
    login(client, ADMIN_EMAIL, ADMIN_PASSWORD)

    response = client.post(
        "/api/admin/integration-clients",
        json={
            "name": "无时区到期时间",
            "scopes": ["suppliers:read"],
            "expires_at": "2035-01-02T03:04:05",
        },
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


def test_create_rejects_expiration_that_is_not_in_the_future(client: TestClient) -> None:
    login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    response = client.post(
        "/api/admin/integration-clients",
        json={
            "name": "过去到期时间",
            "scopes": ["suppliers:read"],
            "expires_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
        },
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


@pytest.mark.parametrize("inactive_kind", ["revoked", "expired"])
def test_rotate_rejects_inactive_credentials(
    client: TestClient,
    inactive_kind: str,
) -> None:
    created = create_client(client, scopes=["suppliers:read"])
    with SessionLocal() as db:
        stored = db.get(IntegrationClient, created["id"])
        assert stored is not None
        if inactive_kind == "revoked":
            stored.is_active = False
        else:
            stored.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()

    response = client.post(f"/api/admin/integration-clients/{created['id']}/rotate")
    assert response.status_code == status.HTTP_409_CONFLICT


def test_create_normalizes_aware_expiration_to_utc(client: TestClient) -> None:
    login(client, ADMIN_EMAIL, ADMIN_PASSWORD)

    response = client.post(
        "/api/admin/integration-clients",
        json={
            "name": f"有时区到期时间-{uuid4().hex[:8]}",
            "scopes": ["suppliers:read"],
            "expires_at": "2035-01-02T03:04:05+08:00",
        },
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert datetime.fromisoformat(response.json()["expires_at"]) == datetime(
        2035,
        1,
        1,
        19,
        4,
        5,
        tzinfo=timezone.utc,
    )


def test_supplier_user_cannot_manage_integration_clients(client: TestClient) -> None:
    created = create_client(client, scopes=["suppliers:read"])
    login(client, SUPPLIER_EMAIL, SUPPLIER_PASSWORD)

    assert client.get(
        "/api/admin/integration-clients"
    ).status_code == status.HTTP_403_FORBIDDEN
    assert client.post(
        "/api/admin/integration-clients",
        json={"name": "越权集成方", "scopes": ["suppliers:read"]},
    ).status_code == status.HTTP_403_FORBIDDEN
    assert client.post(
        f"/api/admin/integration-clients/{created['id']}/rotate"
    ).status_code == status.HTTP_403_FORBIDDEN
    assert client.post(
        f"/api/admin/integration-clients/{created['id']}/revoke"
    ).status_code == status.HTTP_403_FORBIDDEN
