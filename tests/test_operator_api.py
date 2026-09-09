from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from tests.conftest import ADMIN_EMAIL, ADMIN_PASSWORD


def create_approved_operator(client: TestClient) -> tuple[str, str]:
    email = f"workspace-{uuid4().hex[:8]}@example.com"
    created = client.post(
        "/api/public/operator-applications",
        json={"contact_name": "运营主管", "phone": "13600136000", "email": email},
    )
    assert created.status_code == 201
    assert client.post(
        "/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
    ).status_code == 200
    approved = client.post(
        f"/api/admin/operator-applications/{created.json()['id']}/approve", json={}
    )
    assert approved.status_code == 200
    return email, approved.json()["temporary_password"]


def test_operator_can_login_and_use_only_operator_profile(client: TestClient) -> None:
    email, password = create_approved_operator(client)
    login = client.post("/api/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200
    assert login.json()["user"]["role"] == "OPERATOR"
    assert login.json()["user"]["organization_type"] == "OPERATOR"

    profile = client.get("/api/operator/profile")
    assert profile.status_code == 200
    assert profile.json()["contact_name"] == "运营主管"
    assert client.get("/api/dashboard").status_code == 403
    assert client.get("/api/admin/applications").status_code == 403


def test_operator_profile_keeps_required_contact_fields(client: TestClient) -> None:
    email, password = create_approved_operator(client)
    assert client.post("/api/auth/login", json={"email": email, "password": password}).status_code == 200
    assert client.patch("/api/operator/profile", json={"contact_name": ""}).status_code == 422
    updated = client.patch(
        "/api/operator/profile",
        json={"company_name": "新运营公司", "categories": ["户外用品", "户外用品"]},
    )
    assert updated.status_code == 200
    assert updated.json()["company_name"] == "新运营公司"
    assert updated.json()["categories"] == ["户外用品"]
