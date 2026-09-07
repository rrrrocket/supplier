from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url


TEST_DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not TEST_DATABASE_URL.startswith(("postgresql://", "postgresql+psycopg://")):
    raise RuntimeError("测试必须通过 DATABASE_URL 使用独立 PostgreSQL 数据库")
if not (make_url(TEST_DATABASE_URL).database or "").endswith("_test"):
    raise RuntimeError("测试数据库名称必须以 _test 结尾，禁止连接业务数据库")

os.environ["SESSION_SECRET"] = "test-session-secret-with-more-than-thirty-two-characters"
os.environ["APP_ENV"] = "testing"

from app.core.security import hash_password  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models.entities import (  # noqa: E402
    Organization,
    OrganizationType,
    SupplierProfile,
    SupplierStatus,
    User,
    UserRole,
)


SUPPLIER_EMAIL = "supplier-test@example.com"
SUPPLIER_PASSWORD = "SupplierTest123!"
ADMIN_EMAIL = "admin-test@example.com"
ADMIN_PASSWORD = "AdminTest123!"


def create_test_accounts() -> None:
    with SessionLocal() as db:
        platform = Organization(
            code="TEST-PLATFORM",
            name="测试平台组织",
            organization_type=OrganizationType.PLATFORM.value,
        )
        supplier = Organization(
            code="TEST-SUPPLIER",
            name="测试供应商组织",
            organization_type=OrganizationType.SUPPLIER.value,
        )
        db.add_all([platform, supplier])
        db.flush()
        db.add_all(
            [
                User(
                    organization_id=platform.id,
                    email=ADMIN_EMAIL,
                    name="测试平台管理员",
                    role=UserRole.PLATFORM_ADMIN.value,
                    password_hash=hash_password(ADMIN_PASSWORD),
                ),
                User(
                    organization_id=supplier.id,
                    email=SUPPLIER_EMAIL,
                    name="测试供应商",
                    role=UserRole.SUPPLIER.value,
                    password_hash=hash_password(SUPPLIER_PASSWORD),
                ),
                SupplierProfile(
                    organization_id=supplier.id,
                    legal_name="测试供应商有限公司",
                    supplier_type="FACTORY",
                    categories=["工业自动化"],
                    cooperation_modes=["B2B外贸"],
                    status=SupplierStatus.APPROVED.value,
                ),
            ]
        )
        db.commit()


@pytest.fixture(scope="session")
def client() -> TestClient:
    with TestClient(app) as test_client:
        create_test_accounts()
        yield test_client


@pytest.fixture()
def authenticated_client(client: TestClient) -> TestClient:
    response = client.post(
        "/api/auth/login",
        json={
            "email": SUPPLIER_EMAIL,
            "password": SUPPLIER_PASSWORD,
        },
    )
    assert response.status_code == 200
    return client
