from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.entities import (
    ErpBinding,
    EventLog,
    OperatorProfile,
    Organization,
    SupplierProfile,
)
from tests.conftest import (
    ADMIN_EMAIL,
    ADMIN_PASSWORD,
    SUPPLIER_EMAIL,
    SUPPLIER_PASSWORD,
)


def login(client: TestClient, email: str, password: str) -> None:
    assert client.post("/api/auth/login", json={"email": email, "password": password}).status_code == 200


def approved_operator(client: TestClient) -> tuple[str, str, str]:
    email = f"market-{uuid4().hex[:8]}@example.com"
    created = client.post(
        "/api/public/operator-applications",
        json={"contact_name": "市场运营", "phone": "13500135000", "email": email},
    )
    login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    approved = client.post(
        f"/api/admin/operator-applications/{created.json()['id']}/approve", json={}
    )
    assert approved.status_code == 200
    return email, approved.json()["temporary_password"], approved.json()["organization_id"]


def supplier_id_with_contacts() -> str:
    with SessionLocal() as db:
        organization = db.scalar(select(Organization).where(Organization.code == "TEST-SUPPLIER"))
        assert organization is not None
        profile = db.scalar(select(SupplierProfile).where(SupplierProfile.organization_id == organization.id))
        assert profile is not None
        profile.contact_name = "供应联系人"
        profile.contact_phone = "13812345678"
        profile.contact_email = "contact@supplier.example"
        db.commit()
        return organization.id


def operator_id_with_directory_profile(client: TestClient) -> tuple[str, str, str]:
    email, password, operator_id = approved_operator(client)
    with SessionLocal() as db:
        organization = db.get(Organization, operator_id)
        profile = db.scalar(select(OperatorProfile).where(
            OperatorProfile.organization_id == operator_id
        ))
        assert organization is not None
        assert profile is not None
        organization.name = "华东跨境运营"
        profile.company_name = "华东跨境运营有限公司"
        profile.operator_type = "跨境电商代运营"
        profile.province = "浙江省"
        profile.city = "杭州市"
        profile.erp_name = "聚水潭"
        profile.categories = ["工业自动化", "消费电子"]
        profile.sales_channels = ["Amazon", "独立站"]
        profile.target_markets = ["北美", "欧洲"]
        profile.contact_name = "运营联系人"
        profile.contact_phone = "13912345678"
        profile.contact_email = "contact@operator.example"
        db.commit()
    return email, password, operator_id


def test_public_directory_is_paginated_and_masks_contacts(client: TestClient) -> None:
    supplier_id = supplier_id_with_contacts()
    client.post("/api/auth/logout")
    response = client.get("/api/public/suppliers?page=1&page_size=50&category=工业自动化")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 1
    item = next(item for item in body["items"] if item["supplier_id"] == supplier_id)
    assert item["contact_phone"] != "13812345678"
    assert item["contact_email"] != "contact@supplier.example"


def test_operator_detail_returns_full_contact_and_records_access(client: TestClient) -> None:
    supplier_id = supplier_id_with_contacts()
    email, password, _ = approved_operator(client)
    login(client, email, password)
    response = client.get(f"/api/public/suppliers/{supplier_id}")
    assert response.status_code == 200
    assert response.json()["contact_phone"] == "13812345678"
    assert response.json()["contact_email"] == "contact@supplier.example"
    with SessionLocal() as db:
        assert db.scalar(select(EventLog).where(
            EventLog.event_type == "SUPPLIER_CONTACT_VIEWED",
            EventLog.entity_id == supplier_id,
        )) is not None


def test_public_operator_directory_filters_and_masks_contacts(client: TestClient) -> None:
    _, _, operator_id = operator_id_with_directory_profile(client)
    client.post("/api/auth/logout")

    response = client.get(
        "/api/public/operators?page=1&page_size=50"
        "&category=工业自动化&region=浙江省&operator_type=跨境电商代运营&erp_name=聚水潭"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["page"] == 1
    assert body["page_size"] == 50
    item = next(item for item in body["items"] if item["operator_id"] == operator_id)
    assert item["operator_name"] == "华东跨境运营有限公司"
    assert item["categories"] == ["工业自动化", "消费电子"]
    assert item["contact_phone"] == "139****5678"
    assert item["contact_email"] == "c***@operator.example"


def test_supplier_can_view_full_operator_contact_and_access_is_audited(client: TestClient) -> None:
    _, _, operator_id = operator_id_with_directory_profile(client)
    login(client, SUPPLIER_EMAIL, SUPPLIER_PASSWORD)

    response = client.get(f"/api/public/operators/{operator_id}")

    assert response.status_code == 200
    assert response.json()["contact_name"] == "运营联系人"
    assert response.json()["contact_phone"] == "13912345678"
    assert response.json()["contact_email"] == "contact@operator.example"
    with SessionLocal() as db:
        assert db.scalar(select(EventLog).where(
            EventLog.event_type == "OPERATOR_CONTACT_VIEWED",
            EventLog.entity_id == operator_id,
        )) is not None


def test_operator_cannot_use_operator_directory_to_reveal_peer_contacts(client: TestClient) -> None:
    email, password, operator_id = operator_id_with_directory_profile(client)
    login(client, email, password)

    response = client.get(f"/api/public/operators/{operator_id}")

    assert response.status_code == 200
    assert response.json()["contact_phone"] == "139****5678"


def test_public_operator_name_does_not_reveal_contact_when_company_name_is_missing(
    client: TestClient,
) -> None:
    _, _, operator_id = approved_operator(client)
    client.post("/api/auth/logout")

    response = client.get(f"/api/public/operators/{operator_id}")

    assert response.status_code == 200
    body = response.json()
    assert "市场运营" not in body["operator_name"]
    assert body["operator_name"] == "市**的运营团队"

    inferred = client.get("/api/public/operators?keyword=市场运营")
    assert inferred.status_code == 200
    assert all(item["operator_id"] != operator_id for item in inferred.json()["items"])


def test_cooperation_acceptance_creates_binding_and_termination_disables_it(client: TestClient) -> None:
    supplier_id = supplier_id_with_contacts()
    email, password, operator_id = approved_operator(client)
    login(client, email, password)
    created = client.post(
        "/api/operator/cooperations",
        json={"supplier_id": supplier_id, "categories": ["工业自动化"], "message": "申请合作"},
    )
    assert created.status_code == 201
    cooperation_id = created.json()["id"]
    assert client.post("/api/operator/cooperations", json={"supplier_id": supplier_id}).status_code == 409

    login(client, SUPPLIER_EMAIL, SUPPLIER_PASSWORD)
    accepted = client.post(f"/api/supplier-operator/cooperations/{cooperation_id}/accept", json={})
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "ACTIVE"
    binding_id = accepted.json()["binding"]["id"]

    login(client, email, password)
    terminated = client.post(f"/api/operator/cooperations/{cooperation_id}/terminate")
    assert terminated.status_code == 200
    assert terminated.json()["status"] == "TERMINATED"
    with SessionLocal() as db:
        binding = db.get(ErpBinding, binding_id)
        assert binding is not None
        assert binding.operator_id == operator_id
        assert binding.status == "INACTIVE"


def test_supplier_can_terminate_active_cooperation_and_transitions_are_audited(client: TestClient) -> None:
    supplier_id = supplier_id_with_contacts()
    email, password, _ = approved_operator(client)
    login(client, email, password)
    created = client.post("/api/operator/cooperations", json={"supplier_id": supplier_id})
    cooperation_id = created.json()["id"]

    login(client, SUPPLIER_EMAIL, SUPPLIER_PASSWORD)
    assert client.post(f"/api/supplier-operator/cooperations/{cooperation_id}/accept", json={}).status_code == 200
    terminated = client.post(f"/api/supplier-operator/cooperations/{cooperation_id}/terminate")
    assert terminated.status_code == 200
    assert terminated.json()["status"] == "TERMINATED"
    assert terminated.json()["binding"]["status"] == "INACTIVE"

    with SessionLocal() as db:
        events = db.scalars(select(EventLog.event_type).where(EventLog.entity_id == cooperation_id)).all()
        assert "OPERATOR_COOPERATION_CREATED" in events
        assert "OPERATOR_COOPERATION_ACCEPTED" in events
        assert "OPERATOR_COOPERATION_TERMINATED" in events


def test_admin_can_list_operator_accounts_and_cooperations(client: TestClient) -> None:
    supplier_id = supplier_id_with_contacts()
    email, password, operator_id = approved_operator(client)
    login(client, email, password)
    created = client.post("/api/operator/cooperations", json={"supplier_id": supplier_id})
    assert created.status_code == 201

    login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    operators = client.get("/api/admin/operators")
    assert operators.status_code == 200
    assert operators.json()["page"] == 1
    assert operators.json()["page_size"] == 50
    assert any(item["organization_id"] == operator_id for item in operators.json()["items"])
    cooperations = client.get("/api/admin/operator-cooperations")
    assert cooperations.status_code == 200
    assert cooperations.json()["total"] >= 1
    assert any(item["id"] == created.json()["id"] for item in cooperations.json()["items"])
