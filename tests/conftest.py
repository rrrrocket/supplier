from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import and_, delete, or_, select, text
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
from app.db.base import Base  # noqa: E402
from app.main import app  # noqa: E402
from app.models.entities import (  # noqa: E402
    Brand,
    CatalogStatus,
    CommercialMode,
    EventLog,
    IntegrationClient,
    Organization,
    OrganizationType,
    SupplierBrandCooperation,
    SupplierProfile,
    SupplierStatus,
    User,
    UserRole,
)
from app.schemas.integration import INTEGRATION_SCOPES  # noqa: E402


SUPPLIER_EMAIL = "supplier-test@example.com"
SUPPLIER_PASSWORD = "SupplierTest123!"
ADMIN_EMAIL = "admin-test@example.com"
ADMIN_PASSWORD = "AdminTest123!"


def truncate_test_data() -> None:
    database_name = make_url(TEST_DATABASE_URL).database or ""
    if not database_name.endswith("_test"):
        raise RuntimeError("拒绝清理非 _test 数据库")
    table_names = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
    with SessionLocal() as db:
        db.execute(text(f"TRUNCATE TABLE {table_names} CASCADE"))
        db.commit()


@pytest.fixture(scope="session", autouse=True)
def clean_test_database() -> Iterator[None]:
    truncate_test_data()
    yield
    truncate_test_data()


def create_test_accounts() -> None:
    with SessionLocal() as db:
        platform = db.scalar(
            select(Organization).where(Organization.code == "TEST-PLATFORM")
        )
        if platform is None:
            platform = Organization(
                code="TEST-PLATFORM",
                name="测试平台组织",
                organization_type=OrganizationType.PLATFORM.value,
            )
            db.add(platform)
            db.flush()

        supplier = db.scalar(
            select(Organization).where(Organization.code == "TEST-SUPPLIER")
        )
        if supplier is None:
            supplier = Organization(
                code="TEST-SUPPLIER",
                name="测试供应商组织",
                organization_type=OrganizationType.SUPPLIER.value,
            )
            db.add(supplier)
            db.flush()

        admin_user = db.scalar(select(User).where(User.email == ADMIN_EMAIL))
        if admin_user is None:
            admin_user = User(email=ADMIN_EMAIL, name="测试平台管理员")
            db.add(admin_user)
        admin_user.organization_id = platform.id
        admin_user.role = UserRole.PLATFORM_ADMIN.value
        admin_user.password_hash = hash_password(ADMIN_PASSWORD)
        admin_user.is_active = True

        supplier_user = db.scalar(select(User).where(User.email == SUPPLIER_EMAIL))
        if supplier_user is None:
            supplier_user = User(email=SUPPLIER_EMAIL, name="测试供应商")
            db.add(supplier_user)
        supplier_user.organization_id = supplier.id
        supplier_user.role = UserRole.SUPPLIER.value
        supplier_user.password_hash = hash_password(SUPPLIER_PASSWORD)
        supplier_user.is_active = True

        profile = db.scalar(
            select(SupplierProfile).where(
                SupplierProfile.organization_id == supplier.id
            )
        )
        if profile is None:
            profile = SupplierProfile(
                organization_id=supplier.id,
                legal_name="测试供应商有限公司",
                supplier_type="FACTORY",
                categories=["工业自动化"],
                cooperation_modes=["B2B外贸"],
                status=SupplierStatus.APPROVED.value,
            )
            db.add(profile)

        brand = db.scalar(select(Brand).where(Brand.code == "TEST-BRAND"))
        if brand is None:
            brand = Brand(
                code="TEST-BRAND",
                name="TEST",
                normalized_name="test",
                aliases=[],
                status=CatalogStatus.ACTIVE.value,
            )
            db.add(brand)
            db.flush()

        cooperation = db.scalar(
            select(SupplierBrandCooperation).where(
                SupplierBrandCooperation.supplier_id == supplier.id,
                SupplierBrandCooperation.brand_id == brand.id,
                SupplierBrandCooperation.status == CatalogStatus.ACTIVE.value,
            )
        )
        if cooperation is None:
            db.add(
                SupplierBrandCooperation(
                    supplier_id=supplier.id,
                    brand_id=brand.id,
                    commercial_mode=CommercialMode.SELF_PURCHASE.value,
                    status=CatalogStatus.ACTIVE.value,
                )
            )

        alternate_brand = db.scalar(
            select(Brand).where(Brand.code == "TEST-BRAND-ALT")
        )
        if alternate_brand is None:
            alternate_brand = Brand(
                code="TEST-BRAND-ALT",
                name="TEST ALT",
                normalized_name="test alt",
                aliases=[],
                status=CatalogStatus.ACTIVE.value,
            )
            db.add(alternate_brand)
            db.flush()
        alternate_cooperation = db.scalar(
            select(SupplierBrandCooperation).where(
                SupplierBrandCooperation.supplier_id == supplier.id,
                SupplierBrandCooperation.brand_id == alternate_brand.id,
                SupplierBrandCooperation.status == CatalogStatus.ACTIVE.value,
            )
        )
        if alternate_cooperation is None:
            db.add(
                SupplierBrandCooperation(
                    supplier_id=supplier.id,
                    brand_id=alternate_brand.id,
                    commercial_mode=CommercialMode.B2B.value,
                    status=CatalogStatus.ACTIVE.value,
                )
            )
        db.commit()


@pytest.fixture(scope="session")
def client(clean_test_database: Any) -> TestClient:
    del clean_test_database
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


@pytest.fixture()
def integration_client_factory(
    client: TestClient,
) -> Iterator[Callable[[list[str]], dict[str, Any]]]:
    created_ids: list[str] = []

    def create(scopes: list[str]) -> dict[str, Any]:
        login_response = client.post(
            "/api/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        )
        assert login_response.status_code == 200
        response = client.post(
            "/api/admin/integration-clients",
            json={
                "name": f"资源同步测试-{uuid4().hex[:8]}",
                "scopes": scopes,
            },
        )
        assert response.status_code == 201
        result = response.json()
        created_ids.append(result["id"])
        return result

    yield create
    if created_ids:
        with SessionLocal() as db:
            db.execute(
                delete(EventLog).where(
                    or_(
                        and_(
                            EventLog.actor_type == "INTEGRATION_CLIENT",
                            EventLog.actor_id.in_(created_ids),
                        ),
                        and_(
                            EventLog.entity_type == "IntegrationClient",
                            EventLog.entity_id.in_(created_ids),
                        ),
                    )
                )
            )
            db.execute(
                delete(IntegrationClient).where(IntegrationClient.id.in_(created_ids))
            )
            db.commit()


@pytest.fixture()
def integration_client(
    integration_client_factory: Callable[[list[str]], dict[str, Any]],
) -> dict[str, Any]:
    return integration_client_factory(list(INTEGRATION_SCOPES))
