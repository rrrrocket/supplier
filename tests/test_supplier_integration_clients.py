from __future__ import annotations

import json
from uuid import uuid4

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.core.integration_security import create_integration_token
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.entities import (
    EventLog,
    IntegrationClient,
    IntegrationClientType,
    Organization,
    OrganizationType,
    User,
    UserRole,
)
from tests.conftest import SUPPLIER_EMAIL, SUPPLIER_PASSWORD


def login(client: TestClient, email: str, password: str) -> None:
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == status.HTTP_200_OK


def supplier_organization_id() -> str:
    with SessionLocal() as db:
        organization = db.scalar(
            select(Organization).where(Organization.code == "TEST-SUPPLIER")
        )
        assert organization is not None
        return organization.id


def delete_integration_clients(*client_ids: str) -> None:
    if not client_ids:
        return
    with SessionLocal() as db:
        db.execute(
            delete(EventLog).where(
                EventLog.entity_type == "IntegrationClient",
                EventLog.entity_id.in_(client_ids),
            )
        )
        db.execute(delete(IntegrationClient).where(IntegrationClient.id.in_(client_ids)))
        db.commit()


def test_supplier_creates_lists_rotates_and_revokes_only_its_credential(
    client: TestClient,
) -> None:
    login(client, SUPPLIER_EMAIL, SUPPLIER_PASSWORD)
    created_response = client.post(
        "/api/supplier/integration-clients",
        json={
            "name": "  自有   ERP  ",
            "scopes": [
                "supplier-skus:read",
                "supplier-costs:read",
                "supplier-skus:read",
            ],
        },
    )
    assert created_response.status_code == status.HTTP_201_CREATED
    assert created_response.headers["cache-control"] == "no-store"
    created = created_response.json()
    client_id = created["id"]

    try:
        assert created["name"] == "自有 ERP"
        assert created["client_type"] == IntegrationClientType.SUPPLIER.value
        assert created["owner_organization_id"] == supplier_organization_id()
        assert created["scopes"] == ["supplier-skus:read", "supplier-costs:read"]
        assert created["token"].startswith("m1i_")

        listed_response = client.get(
            "/api/supplier/integration-clients", params={"page": 1, "page_size": 20}
        )
        assert listed_response.status_code == status.HTTP_200_OK
        listed = listed_response.json()
        assert listed["total"] == 1
        assert listed["page"] == 1
        assert listed["page_size"] == 20
        assert listed["items"][0]["id"] == client_id
        assert "token" not in listed["items"][0]
        assert created["token"] not in listed_response.text

        rotated_response = client.post(
            f"/api/supplier/integration-clients/{client_id}/rotate"
        )
        assert rotated_response.status_code == status.HTTP_200_OK
        assert rotated_response.headers["cache-control"] == "no-store"
        rotated = rotated_response.json()
        assert rotated["token"] != created["token"]

        revoked_response = client.post(
            f"/api/supplier/integration-clients/{client_id}/revoke"
        )
        assert revoked_response.status_code == status.HTTP_200_OK
        assert revoked_response.json()["is_active"] is False
        assert "token" not in revoked_response.json()

        with SessionLocal() as db:
            stored = db.get(IntegrationClient, client_id)
            events = db.scalars(
                select(EventLog)
                .where(
                    EventLog.entity_type == "IntegrationClient",
                    EventLog.entity_id == client_id,
                )
                .order_by(EventLog.occurred_at)
            ).all()
            assert stored is not None
            issuer = db.scalar(select(User).where(User.email == SUPPLIER_EMAIL))
            assert issuer is not None
            assert stored.issuer_user_id == issuer.id
            assert created["token"] != stored.token_hash
            assert rotated["token"] != stored.token_hash
            assert [event.event_type for event in events] == [
                "SUPPLIER_INTEGRATION_CLIENT_CREATED",
                "SUPPLIER_INTEGRATION_CLIENT_ROTATED",
                "SUPPLIER_INTEGRATION_CLIENT_REVOKED",
            ]
            serialized_events = json.dumps([event.payload for event in events])
            assert created["token"] not in serialized_events
            assert rotated["token"] not in serialized_events
    finally:
        delete_integration_clients(client_id)


def test_supplier_rotation_records_the_current_supplier_user_as_issuer(
    client: TestClient,
) -> None:
    suffix = uuid4().hex[:8]
    second_email = f"supplier-issuer-{suffix}@example.com"
    second_password = "SupplierIssuer123!"
    owner_id = supplier_organization_id()
    with SessionLocal() as db:
        first_user = db.scalar(select(User).where(User.email == SUPPLIER_EMAIL))
        assert first_user is not None
        second_user = User(
            organization_id=owner_id,
            email=second_email,
            name="轮换签发人",
            role=UserRole.SUPPLIER.value,
            password_hash=hash_password(second_password),
        )
        db.add(second_user)
        db.commit()
        first_user_id = first_user.id
        second_user_id = second_user.id

    login(client, SUPPLIER_EMAIL, SUPPLIER_PASSWORD)
    created_response = client.post(
        "/api/supplier/integration-clients",
        json={"name": f"签发人轮换-{suffix}", "scopes": ["suppliers:read"]},
    )
    assert created_response.status_code == status.HTTP_201_CREATED
    created = created_response.json()
    client_id = created["id"]

    try:
        with SessionLocal() as db:
            stored = db.get(IntegrationClient, client_id)
            assert stored is not None
            assert stored.issuer_user_id == first_user_id

        login(client, second_email, second_password)
        rotated_response = client.post(
            f"/api/supplier/integration-clients/{client_id}/rotate"
        )
        assert rotated_response.status_code == status.HTTP_200_OK
        with SessionLocal() as db:
            stored = db.get(IntegrationClient, client_id)
            assert stored is not None
            assert stored.issuer_user_id == second_user_id
    finally:
        delete_integration_clients(client_id)
        with SessionLocal() as db:
            db.execute(delete(User).where(User.id == second_user_id))
            db.commit()


def test_supplier_cannot_manage_another_suppliers_credential(
    client: TestClient,
) -> None:
    suffix = uuid4().hex[:8]
    _, token_prefix, token_hash = create_integration_token()
    with SessionLocal() as db:
        other_supplier = Organization(
            code=f"OTHER-SUPPLIER-{suffix}",
            name=f"其他供应商-{suffix}",
            organization_type=OrganizationType.SUPPLIER.value,
        )
        db.add(other_supplier)
        db.flush()
        issuer = User(
            organization_id=other_supplier.id,
            email=f"other-supplier-issuer-{suffix}@example.com",
            name="其他供应商签发人",
            role=UserRole.SUPPLIER.value,
            password_hash="not-used",
        )
        db.add(issuer)
        db.flush()
        credential = IntegrationClient(
            name=f"其他供应商 ERP-{suffix}",
            client_type=IntegrationClientType.SUPPLIER.value,
            owner_organization_id=other_supplier.id,
            issuer_user_id=issuer.id,
            token_prefix=token_prefix,
            token_hash=token_hash,
            scopes=["supplier-skus:read"],
        )
        db.add(credential)
        db.commit()
        other_supplier_id = other_supplier.id
        issuer_id = issuer.id
        credential_id = credential.id

    try:
        login(client, SUPPLIER_EMAIL, SUPPLIER_PASSWORD)
        assert client.post(
            f"/api/supplier/integration-clients/{credential_id}/rotate"
        ).status_code == status.HTTP_404_NOT_FOUND
        assert client.post(
            f"/api/supplier/integration-clients/{credential_id}/revoke"
        ).status_code == status.HTTP_404_NOT_FOUND
        listed = client.get(
            "/api/supplier/integration-clients", params={"page": 1, "page_size": 20}
        )
        assert listed.status_code == status.HTTP_200_OK
        assert credential_id not in {item["id"] for item in listed.json()["items"]}
    finally:
        delete_integration_clients(credential_id)
        with SessionLocal() as db:
            db.execute(delete(User).where(User.id == issuer_id))
            db.execute(delete(Organization).where(Organization.id == other_supplier_id))
            db.commit()


def test_operator_session_is_forbidden_from_supplier_credential_routes(
    client: TestClient,
) -> None:
    suffix = uuid4().hex[:8]
    email = f"operator-supplier-route-{suffix}@example.com"
    password = "OperatorRoute123!"
    with SessionLocal() as db:
        organization = Organization(
            code=f"OPERATOR-SUPPLIER-ROUTE-{suffix}",
            name=f"运营商-{suffix}",
            organization_type=OrganizationType.OPERATOR.value,
        )
        db.add(organization)
        db.flush()
        user = User(
            organization_id=organization.id,
            email=email,
            name="运营商路由测试",
            role=UserRole.OPERATOR.value,
            password_hash=hash_password(password),
        )
        db.add(user)
        db.commit()
        organization_id = organization.id

    try:
        login(client, email, password)
        response = client.get(
            "/api/supplier/integration-clients", params={"page": 1, "page_size": 20}
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
    finally:
        with SessionLocal() as db:
            db.execute(delete(User).where(User.email == email))
            db.execute(delete(Organization).where(Organization.id == organization_id))
            db.commit()


def test_supplier_credential_list_rejects_unsupported_page_size(
    client: TestClient,
) -> None:
    login(client, SUPPLIER_EMAIL, SUPPLIER_PASSWORD)

    response = client.get(
        "/api/supplier/integration-clients", params={"page": 1, "page_size": 25}
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


@pytest.mark.parametrize("page_size", [20, 50, 100, 200])
def test_supplier_credential_list_accepts_every_supported_page_size(
    client: TestClient,
    page_size: int,
) -> None:
    login(client, SUPPLIER_EMAIL, SUPPLIER_PASSWORD)

    response = client.get(
        "/api/supplier/integration-clients",
        params={"page": 1, "page_size": page_size},
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["page_size"] == page_size
