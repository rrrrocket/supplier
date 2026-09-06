from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient


def login_supplier(client: TestClient) -> None:
    response = client.post(
        "/api/auth/login",
        json={"email": "supplier@matrix-one.tech", "password": "MatrixOne123!"},
    )
    assert response.status_code == 200


def login_admin(client: TestClient) -> None:
    response = client.post(
        "/api/auth/login",
        json={"email": "admin@matrix-one.tech", "password": "MatrixAdmin123!"},
    )
    assert response.status_code == 200
    assert response.json()["user"]["role"] == "PLATFORM_ADMIN"


def create_application(client: TestClient, suffix: str) -> dict:
    response = client.post(
        "/api/public/applications",
        json={
            "company_name": f"管理端测试供应商-{suffix}",
            "company_type": "工贸一体",
            "province": "广东省",
            "city": "东莞市",
            "contact_name": "审核测试人",
            "phone": "13800138001",
            "email": f"approved-{suffix}@example.com",
            "categories": ["工业自动化"],
            "cooperation_modes": ["联营代运营", "B2B外贸"],
            "supports_dropshipping": True,
            "supports_oem": True,
            "has_export_experience": True,
        },
    )
    assert response.status_code == 201
    return response.json()


def test_supplier_cannot_access_admin_api(client: TestClient) -> None:
    login_supplier(client)
    response = client.get("/api/admin/applications")
    assert response.status_code == 403


def test_admin_cannot_use_supplier_business_api(client: TestClient) -> None:
    login_admin(client)
    response = client.get("/api/dashboard")
    assert response.status_code == 403


def test_admin_can_list_and_approve_application(client: TestClient) -> None:
    suffix = uuid4().hex[:8]
    application = create_application(client, suffix)

    login_admin(client)
    applications = client.get("/api/admin/applications")
    assert applications.status_code == 200
    assert any(item["id"] == application["id"] for item in applications.json())

    approval = client.post(
        f"/api/admin/applications/{application['id']}/approve",
        json={"notes": "资料已核验，进入首批试点。"},
    )
    assert approval.status_code == 200
    result = approval.json()
    assert result["status"] == "APPROVED"
    assert result["organization_code"].startswith("SUP-")
    assert result["login_email"] == f"approved-{suffix}@example.com"
    assert len(result["temporary_password"]) >= 12

    suppliers = client.get("/api/admin/suppliers")
    assert suppliers.status_code == 200
    assert any(
        item["organization_id"] == result["organization_id"]
        and item["organization_name"] == f"管理端测试供应商-{suffix}"
        for item in suppliers.json()
    )

    client.post("/api/auth/logout")
    first_login = client.post(
        "/api/auth/login",
        json={
            "email": result["login_email"],
            "password": result["temporary_password"],
        },
    )
    assert first_login.status_code == 200
    assert first_login.json()["user"]["role"] == "SUPPLIER_ADMIN"

    profile = client.get("/api/profile")
    assert profile.status_code == 200
    assert profile.json()["legal_name"] == f"管理端测试供应商-{suffix}"
    assert profile.json()["supplier_type"] == "FACTORY_TRADER"


def test_admin_reject_requires_pending_application(client: TestClient) -> None:
    suffix = uuid4().hex[:8]
    application = create_application(client, suffix)
    login_admin(client)

    rejected = client.post(
        f"/api/admin/applications/{application['id']}/reject",
        json={"notes": "需要补充真实营业执照和产品认证。"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "REJECTED"
    assert "营业执照" in rejected.json()["review_notes"]

    second_review = client.post(
        f"/api/admin/applications/{application['id']}/approve",
        json={"notes": "重复审核"},
    )
    assert second_review.status_code == 409
