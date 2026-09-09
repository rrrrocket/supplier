from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.entities import (
    OperatorApplication,
    OperatorProfile,
    Organization,
    OrganizationType,
    User,
    UserRole,
)
from tests.conftest import ADMIN_EMAIL, ADMIN_PASSWORD


def admin_login(client: TestClient) -> None:
    response = client.post(
        "/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    assert response.status_code == 200


def test_operator_application_only_requires_contact_phone_and_email(client: TestClient) -> None:
    email = f"operator-{uuid4().hex[:8]}@example.com"
    response = client.post(
        "/api/public/operator-applications",
        json={"contact_name": "张运营", "phone": "13800138000", "email": email},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["application_no"].startswith("OPR-")
    with SessionLocal() as db:
        application = db.get(OperatorApplication, body["id"])
        assert application is not None
        assert application.company_name is None
        assert application.sales_channels == []


def test_operator_application_rejects_each_missing_required_field(client: TestClient) -> None:
    payload = {
        "contact_name": "张运营",
        "phone": "13800138000",
        "email": f"required-{uuid4().hex[:8]}@example.com",
    }
    for key in ("contact_name", "phone", "email"):
        invalid = payload.copy()
        invalid.pop(key)
        assert client.post("/api/public/operator-applications", json=invalid).status_code == 422


def test_admin_approval_creates_operator_identity_and_profile(client: TestClient) -> None:
    email = f"approved-{uuid4().hex[:8]}@example.com"
    created = client.post(
        "/api/public/operator-applications",
        json={
            "contact_name": "李运营",
            "phone": "13900139000",
            "email": email,
            "company_name": "测试运营有限公司",
            "categories": ["户外用品"],
        },
    )
    assert created.status_code == 201

    admin_login(client)
    approved = client.post(
        f"/api/admin/operator-applications/{created.json()['id']}/approve",
        json={"notes": "资料通过"},
    )

    assert approved.status_code == 200
    body = approved.json()
    assert body["temporary_password"]
    with SessionLocal() as db:
        organization = db.get(Organization, body["organization_id"])
        assert organization is not None
        assert organization.organization_type == OrganizationType.OPERATOR.value
        user = db.scalar(select(User).where(User.email == email))
        assert user is not None
        assert user.role == UserRole.OPERATOR.value
        profile = db.scalar(
            select(OperatorProfile).where(OperatorProfile.organization_id == organization.id)
        )
        assert profile is not None
        assert profile.contact_name == "李运营"
        assert profile.categories == ["户外用品"]


def test_duplicate_pending_operator_email_is_rejected(client: TestClient) -> None:
    email = f"duplicate-{uuid4().hex[:8]}@example.com"
    payload = {"contact_name": "王运营", "phone": "13700137000", "email": email}
    assert client.post("/api/public/operator-applications", json=payload).status_code == 201
    duplicate = client.post("/api/public/operator-applications", json=payload)
    assert duplicate.status_code == 409
