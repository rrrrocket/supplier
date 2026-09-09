from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.entities import Organization, OrganizationType, User, UserRole


def test_operator_is_a_first_class_organization_and_user_identity() -> None:
    assert OrganizationType.OPERATOR.value == "OPERATOR"
    assert UserRole.OPERATOR.value == "OPERATOR"


def test_new_supplier_user_defaults_to_supplier_role(client: TestClient) -> None:
    suffix = uuid4().hex[:8]
    with SessionLocal() as db:
        organization = Organization(
            code=f"ROLE-{suffix}",
            name="角色默认值测试供应商",
            organization_type=OrganizationType.SUPPLIER.value,
        )
        db.add(organization)
        db.flush()
        user = User(
            organization_id=organization.id,
            email=f"role-{suffix}@example.com",
            name="测试供应商",
            password_hash="test-hash",
        )
        db.add(user)
        db.flush()

        assert user.role == "SUPPLIER"

        db.rollback()


def create_supplier_organization_user(role: str) -> tuple[str, str]:
    suffix = uuid4().hex[:8]
    email = f"role-access-{suffix}@example.com"
    password = "RoleAccessTest123!"
    with SessionLocal() as db:
        organization = db.scalar(
            select(Organization).where(Organization.code == "TEST-SUPPLIER")
        )
        assert organization is not None
        db.add(
            User(
                organization_id=organization.id,
                email=email,
                name="角色权限测试账号",
                role=role,
                password_hash=hash_password(password),
            )
        )
        db.commit()
    return email, password


def test_unknown_role_in_supplier_organization_cannot_use_supplier_api(
    client: TestClient,
) -> None:
    email, password = create_supplier_organization_user("UNKNOWN")
    login = client.post("/api/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200

    response = client.get("/api/dashboard")

    assert response.status_code == 403


def test_platform_role_in_supplier_organization_cannot_use_admin_api(
    client: TestClient,
) -> None:
    email, password = create_supplier_organization_user("PLATFORM_ADMIN")
    login = client.post("/api/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200

    response = client.get("/api/admin/applications")

    assert response.status_code == 403
