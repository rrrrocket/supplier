from __future__ import annotations

import base64
import importlib
import json
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, event, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.api import integration_deps
from app.api.routes import integrations as integration_routes
from app.core.config import get_settings
from app.core.integration_rate_limit import FixedWindowRateLimiter
from app.db.session import SessionLocal, get_db
from app.main import app
from app.models.entities import (
    Brand,
    CatalogStatus,
    CommercialMode,
    EventLog,
    OfferStatus,
    Organization,
    OrganizationType,
    Product,
    SupplierBrandCooperation,
    SupplierOffer,
    SupplierProfile,
    SupplierSku,
    SupplierStatus,
)
from app.services.integration_pagination import decode_cursor, encode_cursor
from tests.conftest import TEST_DATABASE_URL


BASE_PATH = "/api/integrations/v1"


class MutableRateLimitClock:
    def __init__(self) -> None:
        self.current = 0.0

    def __call__(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += seconds


@pytest.fixture()
def low_rate_limit(monkeypatch: pytest.MonkeyPatch) -> MutableRateLimitClock:
    clock = MutableRateLimitClock()
    limiter = FixedWindowRateLimiter(
        max_requests=2,
        window_seconds=60,
        clock=clock,
    )
    monkeypatch.setattr(
        integration_deps,
        "integration_rate_limiter",
        limiter,
    )
    return clock


def auth_headers(integration_client: dict[str, Any]) -> dict[str, str]:
    return {"Authorization": f"Bearer {integration_client['token']}"}


def collect_integration_pages(
    client: TestClient,
    path: str,
    integration_client: dict[str, Any],
    *,
    updated_since: datetime,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "include_inactive": "true",
        "updated_since": updated_since.isoformat(),
        "limit": 1,
    }
    items: list[dict[str, Any]] = []
    while True:
        response = client.get(
            path,
            headers=auth_headers(integration_client),
            params=params,
        )
        assert response.status_code == 200
        payload = response.json()
        items.extend(payload["items"])
        if payload["next_cursor"] is None:
            return items
        params["cursor"] = payload["next_cursor"]


def test_cursor_is_compact_urlsafe_utc_json_and_requires_aware_time() -> None:
    source = datetime.fromisoformat("2031-01-01T16:00:00+08:00")

    cursor = encode_cursor(source, "supplier-id")
    decoded_time, decoded_id = decode_cursor(cursor)
    padding = "=" * (-len(cursor) % 4)
    payload = json.loads(base64.urlsafe_b64decode(cursor + padding))

    assert payload == {"u": "2031-01-01T08:00:00Z", "i": "supplier-id"}
    assert decoded_time == datetime(2031, 1, 1, 8, 0, tzinfo=timezone.utc)
    assert decoded_time.tzinfo is timezone.utc
    assert decoded_id == "supplier-id"
    with pytest.raises(ValueError, match="timezone-aware"):
        encode_cursor(datetime(2031, 1, 1, 8, 0), "supplier-id")


@pytest.fixture(scope="module")
def integration_catalog(client: TestClient) -> dict[str, Any]:
    del client
    suffix = uuid4().hex[:8]
    old_time = datetime(2031, 1, 1, 8, 0, tzinfo=timezone.utc)
    page_time = old_time + timedelta(hours=1)
    profile_time = page_time + timedelta(hours=1)

    with SessionLocal() as db:
        first_supplier = Organization(
            id=f"it-supplier-a-{suffix}",
            code=f"IT-SUP-A-{suffix}",
            name=f"集成供应商 A {suffix}",
            organization_type=OrganizationType.SUPPLIER.value,
            is_active=True,
            created_at=old_time,
            updated_at=page_time,
        )
        second_supplier = Organization(
            id=f"it-supplier-b-{suffix}",
            code=f"IT-SUP-B-{suffix}",
            name=f"集成供应商 B {suffix}",
            organization_type=OrganizationType.SUPPLIER.value,
            is_active=True,
            created_at=old_time,
            updated_at=page_time,
        )
        disabled_supplier = Organization(
            code=f"IT-SUP-DISABLED-{suffix}",
            name=f"已停用供应商 {suffix}",
            organization_type=OrganizationType.SUPPLIER.value,
            is_active=False,
            created_at=old_time,
            updated_at=profile_time,
        )
        pending_supplier = Organization(
            code=f"IT-SUP-PENDING-{suffix}",
            name=f"待审核供应商 {suffix}",
            organization_type=OrganizationType.SUPPLIER.value,
            is_active=True,
            created_at=old_time,
            updated_at=profile_time,
        )
        platform = Organization(
            code=f"IT-PLATFORM-{suffix}",
            name=f"非供应商组织 {suffix}",
            organization_type=OrganizationType.PLATFORM.value,
            is_active=True,
            created_at=old_time,
            updated_at=profile_time,
        )
        db.add_all(
            [
                first_supplier,
                second_supplier,
                disabled_supplier,
                pending_supplier,
                platform,
            ]
        )
        db.flush()

        profiles = [
            SupplierProfile(
                organization_id=first_supplier.id,
                legal_name=first_supplier.name,
                status=SupplierStatus.APPROVED.value,
                created_at=old_time,
                updated_at=profile_time,
            ),
            SupplierProfile(
                organization_id=second_supplier.id,
                legal_name=second_supplier.name,
                status=SupplierStatus.APPROVED.value,
                created_at=old_time,
                updated_at=profile_time,
            ),
            SupplierProfile(
                organization_id=disabled_supplier.id,
                legal_name=disabled_supplier.name,
                status=SupplierStatus.APPROVED.value,
                created_at=old_time,
                updated_at=profile_time,
            ),
            SupplierProfile(
                organization_id=pending_supplier.id,
                legal_name=pending_supplier.name,
                status=SupplierStatus.PENDING.value,
                created_at=old_time,
                updated_at=profile_time,
            ),
        ]
        db.add_all(profiles)

        active_brand = Brand(
            code=f"IT-BRAND-A-{suffix}",
            name=f"集成品牌 A {suffix}",
            normalized_name=f"integration brand a {suffix}",
            aliases=[],
            status=CatalogStatus.ACTIVE.value,
            created_at=old_time,
            updated_at=page_time,
        )
        inactive_cooperation_brand = Brand(
            code=f"IT-BRAND-I-{suffix}",
            name=f"失效合作品牌 {suffix}",
            normalized_name=f"integration brand inactive {suffix}",
            aliases=[],
            status=CatalogStatus.ACTIVE.value,
            created_at=old_time,
            updated_at=page_time,
        )
        other_supplier_brand = Brand(
            code=f"IT-BRAND-O-{suffix}",
            name=f"其他租户品牌 {suffix}",
            normalized_name=f"integration brand other {suffix}",
            aliases=[],
            status=CatalogStatus.ACTIVE.value,
            created_at=old_time,
            updated_at=page_time,
        )
        db.add_all([active_brand, inactive_cooperation_brand, other_supplier_brand])
        db.flush()

        active_cooperation = SupplierBrandCooperation(
            supplier_id=first_supplier.id,
            brand_id=active_brand.id,
            commercial_mode=CommercialMode.SELF_PURCHASE.value,
            status=CatalogStatus.ACTIVE.value,
            created_at=old_time,
            updated_at=page_time,
        )
        inactive_cooperation = SupplierBrandCooperation(
            supplier_id=first_supplier.id,
            brand_id=inactive_cooperation_brand.id,
            commercial_mode=CommercialMode.B2B.value,
            status=CatalogStatus.INACTIVE.value,
            created_at=old_time,
            updated_at=profile_time,
        )
        other_cooperation = SupplierBrandCooperation(
            supplier_id=second_supplier.id,
            brand_id=other_supplier_brand.id,
            commercial_mode=CommercialMode.JOINT_OPERATION.value,
            status=CatalogStatus.ACTIVE.value,
            created_at=old_time,
            updated_at=page_time,
        )
        db.add_all([active_cooperation, inactive_cooperation, other_cooperation])

        active_product = Product(
            created_by_organization_id=first_supplier.id,
            brand_id=active_brand.id,
            name=f"集成商品 A {suffix}",
            model="MODEL-A",
            category="集成测试",
            created_at=old_time,
            updated_at=page_time,
        )
        inactive_product = Product(
            created_by_organization_id=first_supplier.id,
            brand_id=inactive_cooperation_brand.id,
            name=f"失效合作商品 {suffix}",
            model=None,
            category="集成测试",
            created_at=old_time,
            updated_at=page_time,
        )
        other_product = Product(
            created_by_organization_id=second_supplier.id,
            brand_id=other_supplier_brand.id,
            name=f"其他租户商品 {suffix}",
            model="OTHER",
            category="集成测试",
            created_at=old_time,
            updated_at=page_time,
        )
        db.add_all([active_product, inactive_product, other_product])
        db.flush()

        active_sku = SupplierSku(
            supplier_id=first_supplier.id,
            brand_id=active_brand.id,
            product_id=active_product.id,
            supplier_sku_code=f"SKU-A-{suffix}",
            manufacturer_part_number="MPN-A",
            barcode="6900000000001",
            status=CatalogStatus.ACTIVE.value,
            created_at=old_time,
            updated_at=page_time,
        )
        inactive_cooperation_sku = SupplierSku(
            supplier_id=first_supplier.id,
            brand_id=inactive_cooperation_brand.id,
            product_id=inactive_product.id,
            supplier_sku_code=f"SKU-I-{suffix}",
            status=CatalogStatus.ACTIVE.value,
            created_at=old_time,
            updated_at=profile_time,
        )
        inactive_sku = SupplierSku(
            supplier_id=first_supplier.id,
            brand_id=active_brand.id,
            product_id=active_product.id,
            supplier_sku_code=f"SKU-D-{suffix}",
            status=CatalogStatus.INACTIVE.value,
            created_at=old_time,
            updated_at=profile_time,
        )
        other_sku = SupplierSku(
            supplier_id=second_supplier.id,
            brand_id=other_supplier_brand.id,
            product_id=other_product.id,
            supplier_sku_code=f"SKU-O-{suffix}",
            status=CatalogStatus.ACTIVE.value,
            created_at=old_time,
            updated_at=page_time,
        )
        db.add_all([active_sku, inactive_cooperation_sku, inactive_sku, other_sku])
        db.commit()

        return {
            "first_supplier_id": first_supplier.id,
            "second_supplier_id": second_supplier.id,
            "disabled_supplier_id": disabled_supplier.id,
            "pending_supplier_id": pending_supplier.id,
            "platform_id": platform.id,
            "active_brand_id": active_brand.id,
            "inactive_cooperation_brand_id": inactive_cooperation_brand.id,
            "other_supplier_brand_id": other_supplier_brand.id,
            "active_sku_id": active_sku.id,
            "inactive_cooperation_sku_id": inactive_cooperation_sku.id,
            "inactive_sku_id": inactive_sku.id,
            "other_sku_id": other_sku.id,
            "old_time": old_time,
            "page_time": page_time,
            "profile_time": profile_time,
        }


@pytest.fixture(scope="module")
def cost_catalog(client: TestClient) -> dict[str, Any]:
    del client
    suffix = uuid4().hex[:8]
    base_time = datetime(2032, 1, 1, 8, 0, tzinfo=timezone.utc)
    cost_updated_at = base_time + timedelta(hours=1)

    with SessionLocal() as db:
        first_supplier = Organization(
            code=f"COST-SUP-A-{suffix}",
            name=f"成本供应商 A {suffix}",
            organization_type=OrganizationType.SUPPLIER.value,
            is_active=True,
            created_at=base_time,
            updated_at=base_time,
        )
        second_supplier = Organization(
            code=f"COST-SUP-C-{suffix}",
            name=f"成本供应商 C {suffix}",
            organization_type=OrganizationType.SUPPLIER.value,
            is_active=True,
            created_at=base_time,
            updated_at=base_time,
        )
        disabled_supplier = Organization(
            code=f"COST-SUP-OFF-{suffix}",
            name=f"停用成本供应商 {suffix}",
            organization_type=OrganizationType.SUPPLIER.value,
            is_active=False,
            created_at=base_time,
            updated_at=base_time,
        )
        platform = Organization(
            code=f"COST-PLATFORM-{suffix}",
            name=f"非供应商成本组织 {suffix}",
            organization_type=OrganizationType.PLATFORM.value,
            is_active=True,
            created_at=base_time,
            updated_at=base_time,
        )
        missing_profile_supplier = Organization(
            code=f"COST-SUP-NO-PROFILE-{suffix}",
            name=f"无档案成本供应商 {suffix}",
            organization_type=OrganizationType.SUPPLIER.value,
            is_active=True,
            created_at=base_time,
            updated_at=base_time,
        )
        pending_supplier = Organization(
            code=f"COST-SUP-PENDING-{suffix}",
            name=f"待审核成本供应商 {suffix}",
            organization_type=OrganizationType.SUPPLIER.value,
            is_active=True,
            created_at=base_time,
            updated_at=base_time,
        )
        db.add_all(
            [
                first_supplier,
                second_supplier,
                disabled_supplier,
                platform,
                missing_profile_supplier,
                pending_supplier,
            ]
        )
        db.flush()
        db.add_all(
            [
                SupplierProfile(
                    organization_id=first_supplier.id,
                    legal_name=first_supplier.name,
                    status=SupplierStatus.APPROVED.value,
                ),
                SupplierProfile(
                    organization_id=second_supplier.id,
                    legal_name=second_supplier.name,
                    status=SupplierStatus.APPROVED.value,
                ),
                SupplierProfile(
                    organization_id=disabled_supplier.id,
                    legal_name=disabled_supplier.name,
                    status=SupplierStatus.APPROVED.value,
                ),
                SupplierProfile(
                    organization_id=pending_supplier.id,
                    legal_name=pending_supplier.name,
                    status=SupplierStatus.PENDING.value,
                ),
            ]
        )

        active_brand = Brand(
            code=f"COST-BRAND-A-{suffix}",
            name=f"成本模式 A 品牌 {suffix}",
            normalized_name=f"cost mode a brand {suffix}",
            aliases=[],
            status=CatalogStatus.ACTIVE.value,
            created_at=base_time,
            updated_at=base_time,
        )
        b2b_brand = Brand(
            code=f"COST-BRAND-B-{suffix}",
            name=f"成本模式 B 品牌 {suffix}",
            normalized_name=f"cost mode b brand {suffix}",
            aliases=[],
            status=CatalogStatus.ACTIVE.value,
            created_at=base_time,
            updated_at=base_time,
        )
        joint_brand = Brand(
            code=f"COST-BRAND-C-{suffix}",
            name=f"成本模式 C 品牌 {suffix}",
            normalized_name=f"cost mode c brand {suffix}",
            aliases=[],
            status=CatalogStatus.ACTIVE.value,
            created_at=base_time,
            updated_at=base_time,
        )
        inactive_cooperation_brand = Brand(
            code=f"COST-BRAND-OFF-{suffix}",
            name=f"失效成本合作品牌 {suffix}",
            normalized_name=f"cost inactive cooperation brand {suffix}",
            aliases=[],
            status=CatalogStatus.ACTIVE.value,
            created_at=base_time,
            updated_at=base_time,
        )
        db.add_all(
            [
                active_brand,
                b2b_brand,
                joint_brand,
                inactive_cooperation_brand,
            ]
        )
        db.flush()

        db.add_all(
            [
                SupplierBrandCooperation(
                    supplier_id=first_supplier.id,
                    brand_id=active_brand.id,
                    commercial_mode=CommercialMode.SELF_PURCHASE.value,
                    status=CatalogStatus.ACTIVE.value,
                    created_at=base_time,
                    updated_at=base_time,
                ),
                SupplierBrandCooperation(
                    supplier_id=first_supplier.id,
                    brand_id=b2b_brand.id,
                    commercial_mode=CommercialMode.B2B.value,
                    status=CatalogStatus.ACTIVE.value,
                    created_at=base_time,
                    updated_at=base_time,
                ),
                SupplierBrandCooperation(
                    supplier_id=second_supplier.id,
                    brand_id=joint_brand.id,
                    commercial_mode=CommercialMode.JOINT_OPERATION.value,
                    status=CatalogStatus.ACTIVE.value,
                    created_at=base_time,
                    updated_at=base_time,
                ),
                SupplierBrandCooperation(
                    supplier_id=first_supplier.id,
                    brand_id=inactive_cooperation_brand.id,
                    commercial_mode=CommercialMode.SELF_PURCHASE.value,
                    status=CatalogStatus.INACTIVE.value,
                    created_at=base_time,
                    updated_at=base_time,
                ),
            ]
        )

        active_product = Product(
            created_by_organization_id=first_supplier.id,
            brand_id=active_brand.id,
            name=f"成本模式 A 商品 {suffix}",
            model="COST-A",
            category="集成测试",
            created_at=base_time,
            updated_at=base_time,
        )
        b2b_product = Product(
            created_by_organization_id=first_supplier.id,
            brand_id=b2b_brand.id,
            name=f"成本模式 B 商品 {suffix}",
            model="COST-B",
            category="集成测试",
            created_at=base_time,
            updated_at=base_time,
        )
        joint_product = Product(
            created_by_organization_id=second_supplier.id,
            brand_id=joint_brand.id,
            name=f"成本模式 C 商品 {suffix}",
            model="COST-C",
            category="集成测试",
            created_at=base_time,
            updated_at=base_time,
        )
        inactive_cooperation_product = Product(
            created_by_organization_id=first_supplier.id,
            brand_id=inactive_cooperation_brand.id,
            name=f"失效成本合作商品 {suffix}",
            model="COST-OFF",
            category="集成测试",
            created_at=base_time,
            updated_at=base_time,
        )
        db.add_all(
            [
                active_product,
                b2b_product,
                joint_product,
                inactive_cooperation_product,
            ]
        )
        db.flush()

        active_sku = SupplierSku(
            supplier_id=first_supplier.id,
            brand_id=active_brand.id,
            product_id=active_product.id,
            supplier_sku_code=f"COST-A-{suffix}",
            status=CatalogStatus.ACTIVE.value,
            created_at=base_time,
            updated_at=base_time,
        )
        inactive_sku = SupplierSku(
            supplier_id=first_supplier.id,
            brand_id=active_brand.id,
            product_id=active_product.id,
            supplier_sku_code=f"COST-INACTIVE-{suffix}",
            status=CatalogStatus.INACTIVE.value,
            created_at=base_time,
            updated_at=base_time,
        )
        inactive_cooperation_sku = SupplierSku(
            supplier_id=first_supplier.id,
            brand_id=inactive_cooperation_brand.id,
            product_id=inactive_cooperation_product.id,
            supplier_sku_code=f"COST-COOP-OFF-{suffix}",
            status=CatalogStatus.ACTIVE.value,
            created_at=base_time,
            updated_at=base_time,
        )
        b2b_sku = SupplierSku(
            supplier_id=first_supplier.id,
            brand_id=b2b_brand.id,
            product_id=b2b_product.id,
            supplier_sku_code=f"COST-B2B-{suffix}",
            status=CatalogStatus.ACTIVE.value,
            created_at=base_time,
            updated_at=base_time,
        )
        joint_sku = SupplierSku(
            supplier_id=second_supplier.id,
            brand_id=joint_brand.id,
            product_id=joint_product.id,
            supplier_sku_code=f"COST-JOINT-{suffix}",
            status=CatalogStatus.ACTIVE.value,
            created_at=base_time,
            updated_at=base_time,
        )
        missing_offer_sku = SupplierSku(
            supplier_id=first_supplier.id,
            brand_id=active_brand.id,
            product_id=active_product.id,
            supplier_sku_code=f"COST-NO-OFFER-{suffix}",
            status=CatalogStatus.ACTIVE.value,
            created_at=base_time,
            updated_at=base_time,
        )
        paused_offer_sku = SupplierSku(
            supplier_id=first_supplier.id,
            brand_id=active_brand.id,
            product_id=active_product.id,
            supplier_sku_code=f"COST-PAUSED-{suffix}",
            status=CatalogStatus.ACTIVE.value,
            created_at=base_time,
            updated_at=base_time,
        )
        db.add_all(
            [
                active_sku,
                inactive_sku,
                inactive_cooperation_sku,
                b2b_sku,
                joint_sku,
                missing_offer_sku,
                paused_offer_sku,
            ]
        )
        db.flush()

        db.add_all(
            [
                SupplierOffer(
                    organization_id=first_supplier.id,
                    product_id=active_product.id,
                    supplier_sku_id=active_sku.id,
                    price=Decimal("28.5000"),
                    currency="CNY",
                    status=OfferStatus.ACTIVE.value,
                    created_at=base_time,
                    updated_at=cost_updated_at,
                ),
                SupplierOffer(
                    organization_id=first_supplier.id,
                    product_id=active_product.id,
                    supplier_sku_id=paused_offer_sku.id,
                    price=Decimal("99.9900"),
                    currency="CNY",
                    status=OfferStatus.PAUSED.value,
                    created_at=base_time,
                    updated_at=cost_updated_at,
                ),
            ]
        )
        db.commit()

        return {
            "first_supplier_id": first_supplier.id,
            "second_supplier_id": second_supplier.id,
            "disabled_supplier_id": disabled_supplier.id,
            "missing_profile_supplier_id": missing_profile_supplier.id,
            "pending_supplier_id": pending_supplier.id,
            "platform_id": platform.id,
            "active_sku_id": active_sku.id,
            "inactive_sku_id": inactive_sku.id,
            "inactive_cooperation_sku_id": inactive_cooperation_sku.id,
            "b2b_sku_id": b2b_sku.id,
            "other_sku_id": joint_sku.id,
            "missing_offer_sku_id": missing_offer_sku.id,
            "paused_offer_sku_id": paused_offer_sku.id,
            "active_sku_code": active_sku.supplier_sku_code,
            "cost_updated_at": cost_updated_at,
        }


def test_supplier_list_maps_status_uses_latest_source_update_and_hides_inactive(
    client: TestClient,
    integration_client: dict[str, Any],
    integration_catalog: dict[str, Any],
) -> None:
    response = client.get(
        f"{BASE_PATH}/suppliers",
        headers=auth_headers(integration_client),
    )

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"items", "next_cursor"}
    items = {item["supplier_id"]: item for item in payload["items"]}
    assert integration_catalog["first_supplier_id"] in items
    assert integration_catalog["second_supplier_id"] in items
    assert integration_catalog["disabled_supplier_id"] not in items
    assert integration_catalog["pending_supplier_id"] not in items
    assert integration_catalog["platform_id"] not in items
    first = items[integration_catalog["first_supplier_id"]]
    assert set(first) == {
        "supplier_id",
        "supplier_code",
        "supplier_name",
        "status",
        "updated_at",
    }
    assert first["status"] == "ACTIVE"
    assert datetime.fromisoformat(first["updated_at"]) == integration_catalog["profile_time"]


def test_supplier_detail_reports_inactive_suppliers_but_does_not_enumerate_other_orgs(
    client: TestClient,
    integration_client: dict[str, Any],
    integration_catalog: dict[str, Any],
) -> None:
    headers = auth_headers(integration_client)
    inactive_response = client.get(
        f"{BASE_PATH}/suppliers/{integration_catalog['disabled_supplier_id']}",
        headers=headers,
    )
    platform_response = client.get(
        f"{BASE_PATH}/suppliers/{integration_catalog['platform_id']}",
        headers=headers,
    )
    missing_response = client.get(
        f"{BASE_PATH}/suppliers/00000000-0000-0000-0000-000000000000",
        headers=headers,
    )

    assert inactive_response.status_code == 200
    assert inactive_response.json()["status"] == "INACTIVE"
    assert platform_response.status_code == 404
    assert platform_response.json() == missing_response.json()


def test_supplier_updated_since_and_cursor_are_strict_and_duplicate_free(
    client: TestClient,
    integration_client: dict[str, Any],
    integration_catalog: dict[str, Any],
) -> None:
    headers = auth_headers(integration_client)
    path = f"{BASE_PATH}/suppliers"
    params: dict[str, Any] = {
        "updated_since": integration_catalog["page_time"].isoformat(),
        "limit": 1,
    }
    seen: list[str] = []
    seen_updates: list[datetime] = []

    while True:
        response = client.get(path, headers=headers, params=params)
        assert response.status_code == 200
        payload = response.json()
        seen.extend(item["supplier_id"] for item in payload["items"])
        seen_updates.extend(
            datetime.fromisoformat(item["updated_at"]) for item in payload["items"]
        )
        if payload["next_cursor"] is None:
            break
        assert "{" not in payload["next_cursor"]
        params["cursor"] = payload["next_cursor"]

    assert integration_catalog["first_supplier_id"] in seen
    assert integration_catalog["second_supplier_id"] in seen
    assert all(value > integration_catalog["page_time"] for value in seen_updates)
    assert len(seen) == len(set(seen))


def test_supplier_list_can_explicitly_include_inactive_snapshots(
    client: TestClient,
    integration_client: dict[str, Any],
    integration_catalog: dict[str, Any],
) -> None:
    response = client.get(
        f"{BASE_PATH}/suppliers",
        headers=auth_headers(integration_client),
        params={
            "include_inactive": "true",
            "updated_since": integration_catalog["page_time"].isoformat(),
        },
    )

    assert response.status_code == 200
    items = {item["supplier_id"]: item for item in response.json()["items"]}
    assert items[integration_catalog["disabled_supplier_id"]]["status"] == "INACTIVE"
    assert items[integration_catalog["pending_supplier_id"]]["status"] == "INACTIVE"
    assert integration_catalog["platform_id"] not in items


def test_brand_list_is_paginated_active_and_tenant_safe(
    client: TestClient,
    integration_client: dict[str, Any],
    integration_catalog: dict[str, Any],
) -> None:
    response = client.get(
        f"{BASE_PATH}/suppliers/{integration_catalog['first_supplier_id']}/brands",
        headers=auth_headers(integration_client),
        params={"limit": 1},
    )

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"items", "next_cursor"}
    assert payload["next_cursor"] is None
    assert [item["brand_id"] for item in payload["items"]] == [
        integration_catalog["active_brand_id"]
    ]
    assert set(payload["items"][0]) == {
        "brand_id",
        "brand_code",
        "brand_name",
        "commercial_mode",
        "status",
        "updated_at",
    }
    assert payload["items"][0]["commercial_mode"] == "SELF_PURCHASE"
    assert integration_catalog["other_supplier_brand_id"] not in {
        item["brand_id"] for item in payload["items"]
    }


def test_brand_list_cursor_traverses_all_pages_without_duplicates(
    client: TestClient,
    integration_client: dict[str, Any],
) -> None:
    with SessionLocal() as db:
        supplier_id = db.scalar(
            select(Organization.id).where(Organization.code == "TEST-SUPPLIER")
        )
        assert supplier_id is not None
        expected_brand_ids = {
            brand.id
            for brand in db.scalars(
                select(Brand)
                .join(
                    SupplierBrandCooperation,
                    SupplierBrandCooperation.brand_id == Brand.id,
                )
                .where(
                    SupplierBrandCooperation.supplier_id == supplier_id,
                    SupplierBrandCooperation.status == CatalogStatus.ACTIVE.value,
                    Brand.status == CatalogStatus.ACTIVE.value,
                )
            ).all()
        }

    params: dict[str, Any] = {"limit": 1}
    seen: list[str] = []
    while True:
        response = client.get(
            f"{BASE_PATH}/suppliers/{supplier_id}/brands",
            headers=auth_headers(integration_client),
            params=params,
        )
        assert response.status_code == 200
        payload = response.json()
        seen.extend(item["brand_id"] for item in payload["items"])
        if payload["next_cursor"] is None:
            break
        params["cursor"] = payload["next_cursor"]

    assert set(seen) == expected_brand_ids
    assert len(seen) == len(set(seen))


def test_brand_updated_since_is_strict_for_visible_brand_changes(
    client: TestClient,
    integration_client: dict[str, Any],
    integration_catalog: dict[str, Any],
) -> None:
    brand_id = integration_catalog["active_brand_id"]
    watermark = integration_catalog["profile_time"]
    changed_at = watermark + timedelta(minutes=30)
    with SessionLocal() as db:
        brand = db.get(Brand, brand_id)
        assert brand is not None
        original_updated_at = brand.updated_at
        brand.updated_at = changed_at
        db.commit()

    try:
        response = client.get(
            f"{BASE_PATH}/suppliers/{integration_catalog['first_supplier_id']}/brands",
            headers=auth_headers(integration_client),
            params={"updated_since": watermark.isoformat()},
        )
        strict_response = client.get(
            f"{BASE_PATH}/suppliers/{integration_catalog['first_supplier_id']}/brands",
            headers=auth_headers(integration_client),
            params={"updated_since": changed_at.isoformat()},
        )

        assert response.status_code == 200
        assert [item["brand_id"] for item in response.json()["items"]] == [brand_id]
        assert datetime.fromisoformat(response.json()["items"][0]["updated_at"]) == changed_at
        assert strict_response.status_code == 200
        assert strict_response.json()["items"] == []
    finally:
        with SessionLocal() as db:
            brand = db.get(Brand, brand_id)
            assert brand is not None
            brand.updated_at = original_updated_at
            db.commit()


def test_sku_list_derives_active_cooperation_and_include_inactive_snapshot(
    client: TestClient,
    integration_client: dict[str, Any],
    integration_catalog: dict[str, Any],
) -> None:
    path = f"{BASE_PATH}/suppliers/{integration_catalog['first_supplier_id']}/skus"
    headers = auth_headers(integration_client)

    active_response = client.get(path, headers=headers)
    inactive_response = client.get(
        path,
        headers=headers,
        params={"include_inactive": "true"},
    )

    assert active_response.status_code == 200
    active_payload = active_response.json()
    assert set(active_payload) == {"items", "next_cursor"}
    assert [item["supplier_sku_id"] for item in active_payload["items"]] == [
        integration_catalog["active_sku_id"]
    ]
    active = active_payload["items"][0]
    assert set(active) == {
        "supplier_sku_id",
        "supplier_sku_code",
        "brand_id",
        "brand_name",
        "product_name",
        "model",
        "manufacturer_part_number",
        "barcode",
        "commercial_mode",
        "status",
        "updated_at",
    }
    assert active["commercial_mode"] == "SELF_PURCHASE"
    assert active["status"] == "ACTIVE"
    assert "client_sku_id" not in active

    assert inactive_response.status_code == 200
    inactive_items = {
        item["supplier_sku_id"]: item for item in inactive_response.json()["items"]
    }
    assert inactive_items[integration_catalog["inactive_sku_id"]]["status"] == "INACTIVE"
    cooperation_inactive = inactive_items[
        integration_catalog["inactive_cooperation_sku_id"]
    ]
    assert cooperation_inactive["status"] == "INACTIVE"
    assert cooperation_inactive["commercial_mode"] == "B2B"
    assert integration_catalog["other_sku_id"] not in inactive_items


def test_sku_updated_since_cursor_uses_id_tiebreak_for_identical_timestamps(
    client: TestClient,
    integration_client: dict[str, Any],
    integration_catalog: dict[str, Any],
) -> None:
    supplier_id = integration_catalog["first_supplier_id"]
    brand_id = integration_catalog["active_brand_id"]
    watermark = integration_catalog["profile_time"]
    changed_at = watermark + timedelta(minutes=45)
    suffix = uuid4().hex[:8]
    with SessionLocal() as db:
        product = Product(
            created_by_organization_id=supplier_id,
            brand_id=brand_id,
            name=f"游标测试商品 {suffix}",
            model="CURSOR-MODEL",
            category="集成测试",
            created_at=watermark,
            updated_at=watermark,
        )
        db.add(product)
        db.flush()
        sku_ids = [f"it-cursor-a-{suffix}", f"it-cursor-b-{suffix}"]
        db.add_all(
            [
                SupplierSku(
                    id=sku_id,
                    supplier_id=supplier_id,
                    brand_id=brand_id,
                    product_id=product.id,
                    supplier_sku_code=f"CURSOR-{index}-{suffix}",
                    status=CatalogStatus.ACTIVE.value,
                    created_at=watermark,
                    updated_at=changed_at,
                )
                for index, sku_id in enumerate(sku_ids, start=1)
            ]
        )
        db.commit()
        product_id = product.id

    try:
        items = collect_integration_pages(
            client,
            f"{BASE_PATH}/suppliers/{supplier_id}/skus",
            integration_client,
            updated_since=watermark,
        )
        strict_items = collect_integration_pages(
            client,
            f"{BASE_PATH}/suppliers/{supplier_id}/skus",
            integration_client,
            updated_since=changed_at,
        )

        assert [item["supplier_sku_id"] for item in items] == sorted(sku_ids)
        assert {datetime.fromisoformat(item["updated_at"]) for item in items} == {
            changed_at
        }
        assert strict_items == []
    finally:
        with SessionLocal() as db:
            db.execute(delete(SupplierSku).where(SupplierSku.id.in_(sku_ids)))
            db.flush()
            product = db.get(Product, product_id)
            assert product is not None
            db.delete(product)
            db.commit()


def test_nested_incremental_sync_tracks_supplier_and_profile_status_changes_once(
    client: TestClient,
    integration_client: dict[str, Any],
    integration_catalog: dict[str, Any],
) -> None:
    supplier_id = integration_catalog["first_supplier_id"]
    brand_path = f"{BASE_PATH}/suppliers/{supplier_id}/brands"
    sku_path = f"{BASE_PATH}/suppliers/{supplier_id}/skus"
    initial_watermark = integration_catalog["profile_time"]
    phase_times = [
        initial_watermark + timedelta(hours=1),
        initial_watermark + timedelta(hours=2),
        initial_watermark + timedelta(hours=3),
        initial_watermark + timedelta(hours=4),
    ]

    with SessionLocal() as db:
        supplier = db.get(Organization, supplier_id)
        profile = db.scalar(
            select(SupplierProfile).where(
                SupplierProfile.organization_id == supplier_id
            )
        )
        assert supplier is not None
        assert profile is not None
        original_supplier_active = supplier.is_active
        original_supplier_updated_at = supplier.updated_at
        original_profile_status = profile.status
        original_profile_updated_at = profile.updated_at

    expected_brand_ids = {
        integration_catalog["active_brand_id"],
        integration_catalog["inactive_cooperation_brand_id"],
    }
    expected_sku_ids = {
        integration_catalog["active_sku_id"],
        integration_catalog["inactive_sku_id"],
        integration_catalog["inactive_cooperation_sku_id"],
    }

    try:
        phases = [
            ("supplier", False, phase_times[0], "INACTIVE"),
            ("supplier", True, phase_times[1], "ACTIVE"),
            ("profile", SupplierStatus.PENDING.value, phase_times[2], "INACTIVE"),
            ("profile", SupplierStatus.APPROVED.value, phase_times[3], "ACTIVE"),
        ]
        previous_watermark = initial_watermark
        for source, value, changed_at, active_resource_status in phases:
            with SessionLocal() as db:
                supplier = db.get(Organization, supplier_id)
                profile = db.scalar(
                    select(SupplierProfile).where(
                        SupplierProfile.organization_id == supplier_id
                    )
                )
                assert supplier is not None
                assert profile is not None
                if source == "supplier":
                    supplier.is_active = bool(value)
                    supplier.updated_at = changed_at
                else:
                    profile.status = str(value)
                    profile.updated_at = changed_at
                db.commit()

            brand_items = collect_integration_pages(
                client,
                brand_path,
                integration_client,
                updated_since=previous_watermark,
            )
            sku_items = collect_integration_pages(
                client,
                sku_path,
                integration_client,
                updated_since=previous_watermark,
            )

            assert {item["brand_id"] for item in brand_items} == expected_brand_ids
            assert len(brand_items) == len(expected_brand_ids)
            assert {datetime.fromisoformat(item["updated_at"]) for item in brand_items} == {
                changed_at
            }
            assert {item["supplier_sku_id"] for item in sku_items} == expected_sku_ids
            assert len(sku_items) == len(expected_sku_ids)
            assert {datetime.fromisoformat(item["updated_at"]) for item in sku_items} == {
                changed_at
            }

            brand_by_id = {item["brand_id"]: item for item in brand_items}
            sku_by_id = {item["supplier_sku_id"]: item for item in sku_items}
            assert (
                brand_by_id[integration_catalog["active_brand_id"]]["status"]
                == active_resource_status
            )
            assert (
                sku_by_id[integration_catalog["active_sku_id"]]["status"]
                == active_resource_status
            )
            previous_watermark = changed_at
    finally:
        with SessionLocal() as db:
            supplier = db.get(Organization, supplier_id)
            profile = db.scalar(
                select(SupplierProfile).where(
                    SupplierProfile.organization_id == supplier_id
                )
            )
            assert supplier is not None
            assert profile is not None
            supplier.is_active = original_supplier_active
            supplier.updated_at = original_supplier_updated_at
            profile.status = original_profile_status
            profile.updated_at = original_profile_updated_at
            db.commit()


def test_include_inactive_exposes_tenant_owned_sku_without_cooperation_history(
    client: TestClient,
    integration_client: dict[str, Any],
    integration_catalog: dict[str, Any],
) -> None:
    suffix = uuid4().hex[:8]
    supplier_id = integration_catalog["first_supplier_id"]
    with SessionLocal() as db:
        brand = Brand(
            code=f"IT-ORPHAN-{suffix}",
            name=f"无合作历史品牌 {suffix}",
            normalized_name=f"integration orphan {suffix}",
            aliases=[],
            status=CatalogStatus.ACTIVE.value,
        )
        db.add(brand)
        db.flush()
        product = Product(
            created_by_organization_id=supplier_id,
            brand_id=brand.id,
            name=f"无合作历史商品 {suffix}",
            model="ORPHAN-MODEL",
            category="集成测试",
        )
        db.add(product)
        db.flush()
        orphan_sku = SupplierSku(
            supplier_id=supplier_id,
            brand_id=brand.id,
            product_id=product.id,
            supplier_sku_code=f"ORPHAN-SKU-{suffix}",
            status=CatalogStatus.ACTIVE.value,
        )
        db.add(orphan_sku)
        db.commit()
        orphan_sku_id = orphan_sku.id

    path = f"{BASE_PATH}/suppliers/{supplier_id}/skus"
    active_response = client.get(path, headers=auth_headers(integration_client))
    inactive_response = client.get(
        path,
        headers=auth_headers(integration_client),
        params={"include_inactive": "true"},
    )
    other_supplier_response = client.get(
        f"{BASE_PATH}/suppliers/{integration_catalog['second_supplier_id']}/skus",
        headers=auth_headers(integration_client),
        params={"include_inactive": "true"},
    )

    assert active_response.status_code == 200
    assert orphan_sku_id not in {
        item["supplier_sku_id"] for item in active_response.json()["items"]
    }
    assert inactive_response.status_code == 200
    orphan = next(
        item
        for item in inactive_response.json()["items"]
        if item["supplier_sku_id"] == orphan_sku_id
    )
    assert orphan["status"] == "INACTIVE"
    assert orphan["commercial_mode"] is None
    assert other_supplier_response.status_code == 200
    assert orphan_sku_id not in {
        item["supplier_sku_id"] for item in other_supplier_response.json()["items"]
    }


def test_decode_cursor_rejects_noncanonical_equivalent_encodings() -> None:
    timestamp = datetime(2031, 1, 1, 8, 0, tzinfo=timezone.utc)
    canonical = encode_cursor(timestamp, "supplier-id")

    def encoded(payload: bytes) -> str:
        return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")

    noncanonical_values = [
        canonical + "=",
        encoded(b'{"i":"supplier-id","u":"2031-01-01T08:00:00Z"}'),
        encoded(b'{"u": "2031-01-01T08:00:00Z", "i": "supplier-id"}'),
        encoded(b'{"u":"2031-01-01T08:00:00+00:00","i":"supplier-id"}'),
    ]

    for value in noncanonical_values:
        with pytest.raises(HTTPException) as exc_info:
            decode_cursor(value)
        assert exc_info.value.status_code == 400
        assert exc_info.value.detail["code"] == "INVALID_CURSOR"


@pytest.mark.parametrize(
    ("scope", "path_template"),
    [
        ("supplier-brands:read", "/suppliers"),
        ("supplier-skus:read", "/suppliers/{first_supplier_id}"),
        ("suppliers:read", "/suppliers/{first_supplier_id}/brands"),
        ("supplier-brands:read", "/suppliers/{first_supplier_id}/skus"),
    ],
)
def test_each_resource_path_requires_its_own_scope(
    client: TestClient,
    integration_client_factory: Callable[[list[str]], dict[str, Any]],
    integration_catalog: dict[str, Any],
    scope: str,
    path_template: str,
) -> None:
    scoped_client = integration_client_factory([scope])
    path = path_template.format(**integration_catalog)

    response = client.get(f"{BASE_PATH}{path}", headers=auth_headers(scoped_client))

    assert response.status_code == 403


@pytest.mark.parametrize(
    "path_template",
    [
        "/suppliers",
        "/suppliers/{first_supplier_id}/brands",
        "/suppliers/{first_supplier_id}/skus",
    ],
)
def test_all_list_limits_are_capped_at_500(
    client: TestClient,
    integration_client: dict[str, Any],
    integration_catalog: dict[str, Any],
    path_template: str,
) -> None:
    path = path_template.format(**integration_catalog)

    response = client.get(
        f"{BASE_PATH}{path}",
        headers=auth_headers(integration_client),
        params={"limit": 501},
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("path_template", "cursor"),
    [
        ("/suppliers", "not-a-valid-cursor"),
        ("/suppliers", "a" * 2049),
        ("/suppliers/{first_supplier_id}/brands", "not-a-valid-cursor"),
        ("/suppliers/{first_supplier_id}/brands", "a" * 2049),
        ("/suppliers/{first_supplier_id}/skus", "not-a-valid-cursor"),
        ("/suppliers/{first_supplier_id}/skus", "a" * 2049),
    ],
)
def test_all_lists_reject_invalid_cursor_with_stable_error_code(
    client: TestClient,
    integration_client: dict[str, Any],
    integration_catalog: dict[str, Any],
    path_template: str,
    cursor: str,
) -> None:
    path = path_template.format(**integration_catalog)

    response = client.get(
        f"{BASE_PATH}{path}",
        headers=auth_headers(integration_client),
        params={"cursor": cursor},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "INVALID_CURSOR"


def test_nested_resources_reject_non_supplier_and_unknown_ids_identically(
    client: TestClient,
    integration_client: dict[str, Any],
    integration_catalog: dict[str, Any],
) -> None:
    headers = auth_headers(integration_client)
    missing_id = "00000000-0000-0000-0000-000000000000"

    for resource in ("brands", "skus"):
        supplier_response = client.get(
            f"{BASE_PATH}/suppliers/{integration_catalog['first_supplier_id']}/{resource}",
            headers=headers,
        )
        platform_response = client.get(
            f"{BASE_PATH}/suppliers/{integration_catalog['platform_id']}/{resource}",
            headers=headers,
        )
        missing_response = client.get(
            f"{BASE_PATH}/suppliers/{missing_id}/{resource}",
            headers=headers,
        )
        assert supplier_response.status_code == 200
        assert platform_response.status_code == 404
        assert platform_response.json() == missing_response.json()


def test_single_cost_returns_exact_current_mode_a_offer_and_aggregate_audit(
    client: TestClient,
    integration_client: dict[str, Any],
    cost_catalog: dict[str, Any],
) -> None:
    request_id = "caller-request-success-001"
    headers = auth_headers(integration_client)
    headers["X-Request-ID"] = request_id
    response = client.get(
        f"{BASE_PATH}/suppliers/{cost_catalog['first_supplier_id']}"
        f"/skus/{cost_catalog['active_sku_id']}/cost",
        headers=headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "supplier_id": cost_catalog["first_supplier_id"],
        "supplier_sku_id": cost_catalog["active_sku_id"],
        "supplier_sku_code": cost_catalog["active_sku_code"],
        "cost_price": "28.5000",
        "currency": "CNY",
        "cost_updated_at": cost_catalog["cost_updated_at"].isoformat().replace(
            "+00:00", "Z"
        ),
    }

    with SessionLocal() as db:
        events = db.scalars(
            select(EventLog).where(
                EventLog.event_type == "INTEGRATION_SKU_COSTS_QUERIED",
                EventLog.actor_id == integration_client["id"],
            )
        ).all()
    assert len(events) == 1
    event = events[0]
    assert event.organization_id is None
    assert event.actor_type == "INTEGRATION_CLIENT"
    assert event.entity_type == "IntegrationClient"
    assert event.entity_id == integration_client["id"]
    assert event.payload["endpoint"] == (
        f"{BASE_PATH}/suppliers/{cost_catalog['first_supplier_id']}"
        f"/skus/{cost_catalog['active_sku_id']}/cost"
    )
    assert event.payload["result_count"] == 1
    assert event.payload["error_count"] == 0
    assert event.payload["request_id"] == request_id
    assert set(event.payload) == {
        "request_id",
        "endpoint",
        "result_count",
        "error_count",
    }
    assert "28.5000" not in json.dumps(event.payload)
    assert integration_client["token"] not in json.dumps(event.payload)


@pytest.mark.parametrize(
    "supplier_key",
    ["missing_profile_supplier_id", "pending_supplier_id"],
    ids=["missing-profile", "pending-profile"],
)
def test_single_cost_rejects_supplier_without_approved_profile(
    client: TestClient,
    integration_client: dict[str, Any],
    cost_catalog: dict[str, Any],
    supplier_key: str,
) -> None:
    response = client.get(
        f"{BASE_PATH}/suppliers/{cost_catalog[supplier_key]}"
        f"/skus/{cost_catalog['active_sku_id']}/cost",
        headers=auth_headers(integration_client),
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": {"code": "SUPPLIER_INACTIVE", "message": "供应商已停用"}
    }


def test_batch_cost_rejects_suppliers_without_approved_profiles(
    client: TestClient,
    integration_client: dict[str, Any],
    cost_catalog: dict[str, Any],
) -> None:
    client_sku_ids = ["missing-profile", "pending-profile"]
    response = client.post(
        f"{BASE_PATH}/sku-costs/query",
        headers=auth_headers(integration_client),
        json={
            "items": [
                {
                    "client_sku_id": client_sku_id,
                    "supplier_id": cost_catalog[supplier_key],
                    "supplier_sku_id": cost_catalog["active_sku_id"],
                }
                for client_sku_id, supplier_key in zip(
                    client_sku_ids,
                    ("missing_profile_supplier_id", "pending_supplier_id"),
                    strict=True,
                )
            ]
        },
    )

    assert response.status_code == 200
    assert response.json()["items"] == [
        {
            "client_sku_id": client_sku_id,
            "supplier_id": cost_catalog[supplier_key],
            "supplier_sku_id": cost_catalog["active_sku_id"],
            "status": "ERROR",
            "error_code": "SUPPLIER_INACTIVE",
            "message": "供应商已停用",
        }
        for client_sku_id, supplier_key in zip(
            client_sku_ids,
            ("missing_profile_supplier_id", "pending_supplier_id"),
            strict=True,
        )
    ]


def test_cost_audit_reuses_the_same_caller_request_id_on_retry(
    client: TestClient,
    integration_client: dict[str, Any],
    cost_catalog: dict[str, Any],
) -> None:
    request_id = "caller-retry-id-001"
    headers = auth_headers(integration_client)
    headers["X-Request-ID"] = request_id
    path = (
        f"{BASE_PATH}/suppliers/{cost_catalog['first_supplier_id']}"
        f"/skus/{cost_catalog['active_sku_id']}/cost"
    )

    first = client.get(path, headers=headers)
    second = client.get(path, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    with SessionLocal() as db:
        events = db.scalars(
            select(EventLog).where(
                EventLog.event_type == "INTEGRATION_SKU_COSTS_QUERIED",
                EventLog.actor_id == integration_client["id"],
            )
        ).all()
    assert len(events) == 2
    assert [event.payload["request_id"] for event in events] == [request_id, request_id]


@pytest.mark.parametrize(
    "request_id",
    [None, "   "],
    ids=["missing-header", "blank-header"],
)
def test_cost_audit_uses_uuid_when_request_id_is_missing_or_blank(
    client: TestClient,
    integration_client: dict[str, Any],
    cost_catalog: dict[str, Any],
    request_id: str | None,
) -> None:
    headers = auth_headers(integration_client)
    if request_id is not None:
        headers["X-Request-ID"] = request_id

    response = client.get(
        f"{BASE_PATH}/suppliers/{cost_catalog['first_supplier_id']}"
        f"/skus/{cost_catalog['active_sku_id']}/cost",
        headers=headers,
    )

    assert response.status_code == 200
    with SessionLocal() as db:
        events = db.scalars(
            select(EventLog).where(
                EventLog.event_type == "INTEGRATION_SKU_COSTS_QUERIED",
                EventLog.actor_id == integration_client["id"],
            )
        ).all()
    assert len(events) == 1
    fallback = events[0].payload["request_id"]
    assert str(UUID(fallback)) == fallback


def test_cost_audit_waits_for_request_db_release_with_single_connection_pool(
    integration_client: dict[str, Any],
    cost_catalog: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    single_connection_engine = create_engine(
        TEST_DATABASE_URL,
        pool_size=1,
        max_overflow=0,
        pool_timeout=0.1,
    )
    SingleConnectionSession = sessionmaker(
        bind=single_connection_engine,
        autoflush=False,
        expire_on_commit=False,
    )
    integration_client_updates = 0

    @event.listens_for(single_connection_engine, "before_cursor_execute")
    def count_integration_client_updates(
        _connection: Any,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        _executemany: bool,
    ) -> None:
        nonlocal integration_client_updates
        if statement.lower().startswith("update integration_clients"):
            integration_client_updates += 1

    def get_single_connection_db() -> Iterator[Session]:
        with SingleConnectionSession() as db:
            yield db

    app.dependency_overrides[get_db] = get_single_connection_db
    monkeypatch.setattr(
        integration_deps,
        "SessionLocal",
        SingleConnectionSession,
    )
    monkeypatch.setattr(
        integration_routes,
        "SessionLocal",
        SingleConnectionSession,
    )
    try:
        with TestClient(app, raise_server_exceptions=False) as isolated_client:
            response = isolated_client.get(
                f"{BASE_PATH}/suppliers/{cost_catalog['first_supplier_id']}"
                f"/skus/{cost_catalog['active_sku_id']}/cost",
                headers=auth_headers(integration_client),
            )
    finally:
        app.dependency_overrides.pop(get_db, None)
        single_connection_engine.dispose()

    assert response.status_code == 200
    with SessionLocal() as db:
        events = db.scalars(
            select(EventLog).where(
                EventLog.event_type == "INTEGRATION_SKU_COSTS_QUERIED",
                EventLog.actor_id == integration_client["id"],
            )
        ).all()
    assert len(events) == 1
    assert integration_client_updates == 1


def test_valid_client_malformed_json_is_authenticated_and_audited(
    client: TestClient,
    integration_client: dict[str, Any],
) -> None:
    headers = auth_headers(integration_client)
    headers["Content-Type"] = "application/json"

    response = client.post(
        f"{BASE_PATH}/sku-costs/query",
        headers=headers,
        content=b'{"items": [',
    )

    assert response.status_code == 400
    with SessionLocal() as db:
        events = db.scalars(
            select(EventLog).where(
                EventLog.event_type == "INTEGRATION_SKU_COSTS_QUERIED",
                EventLog.actor_id == integration_client["id"],
            )
        ).all()
    assert len(events) == 1
    assert events[0].payload["result_count"] == 0
    assert events[0].payload["error_count"] == 1


@pytest.mark.parametrize(
    "authorization",
    [
        None,
        "Bearer invalid",
        "Bearer m1i_unknown-token-value",
    ],
    ids=["missing", "malformed", "unknown"],
)
def test_unidentified_client_malformed_json_does_not_fabricate_audit_actor(
    client: TestClient,
    authorization: str | None,
) -> None:
    headers = {"Content-Type": "application/json"}
    if authorization is not None:
        headers["Authorization"] = authorization
    with SessionLocal() as db:
        before = db.scalar(
            select(func.count(EventLog.id)).where(
                EventLog.event_type == "INTEGRATION_SKU_COSTS_QUERIED"
            )
        )

    response = client.post(
        f"{BASE_PATH}/sku-costs/query",
        headers=headers,
        content=b'{"items": [',
    )

    assert response.status_code == 400
    with SessionLocal() as db:
        after = db.scalar(
            select(func.count(EventLog.id)).where(
                EventLog.event_type == "INTEGRATION_SKU_COSTS_QUERIED"
            )
        )
    assert after == before


@pytest.mark.parametrize(
    (
        "supplier_key",
        "sku_key",
        "expected_status",
        "expected_code",
        "expected_message",
    ),
    [
        (
            "missing",
            "active_sku_id",
            404,
            "SUPPLIER_NOT_FOUND",
            "供应商不存在",
        ),
        (
            "platform_id",
            "active_sku_id",
            404,
            "SUPPLIER_NOT_FOUND",
            "供应商不存在",
        ),
        (
            "disabled_supplier_id",
            "missing",
            409,
            "SUPPLIER_INACTIVE",
            "供应商已停用",
        ),
        (
            "first_supplier_id",
            "missing",
            404,
            "SKU_NOT_FOUND",
            "Supplier SKU 不存在",
        ),
        (
            "first_supplier_id",
            "other_sku_id",
            409,
            "SKU_SUPPLIER_MISMATCH",
            "Supplier SKU 不属于该供应商",
        ),
        (
            "first_supplier_id",
            "inactive_sku_id",
            409,
            "SKU_INACTIVE",
            "Supplier SKU 已停用",
        ),
        (
            "first_supplier_id",
            "inactive_cooperation_sku_id",
            409,
            "BRAND_COOPERATION_INACTIVE",
            "品牌合作关系未启用",
        ),
        (
            "first_supplier_id",
            "b2b_sku_id",
            409,
            "NOT_SELF_PURCHASE",
            "该货号所属品牌不是自营采购模式",
        ),
        (
            "second_supplier_id",
            "other_sku_id",
            409,
            "NOT_SELF_PURCHASE",
            "该货号所属品牌不是自营采购模式",
        ),
        (
            "first_supplier_id",
            "missing_offer_sku_id",
            409,
            "COST_PRICE_MISSING",
            "当前成本价不存在",
        ),
        (
            "first_supplier_id",
            "paused_offer_sku_id",
            409,
            "COST_PRICE_MISSING",
            "当前成本价不存在",
        ),
    ],
    ids=[
        "supplier-not-found",
        "non-supplier-organization",
        "supplier-inactive-before-missing-sku",
        "sku-not-found",
        "supplier-mismatch-before-sku-status",
        "sku-inactive",
        "cooperation-inactive",
        "mode-b",
        "mode-c",
        "offer-missing",
        "offer-not-active",
    ],
)
def test_single_cost_maps_each_business_failure_after_ordered_validation(
    client: TestClient,
    integration_client: dict[str, Any],
    cost_catalog: dict[str, Any],
    supplier_key: str,
    sku_key: str,
    expected_status: int,
    expected_code: str,
    expected_message: str,
) -> None:
    supplier_id = (
        "00000000-0000-0000-0000-000000000001"
        if supplier_key == "missing"
        else cost_catalog[supplier_key]
    )
    supplier_sku_id = (
        "00000000-0000-0000-0000-000000000002"
        if sku_key == "missing"
        else cost_catalog[sku_key]
    )

    response = client.get(
        f"{BASE_PATH}/suppliers/{supplier_id}/skus/{supplier_sku_id}/cost",
        headers=auth_headers(integration_client),
    )

    assert response.status_code == expected_status
    assert response.json() == {
        "detail": {"code": expected_code, "message": expected_message}
    }
    with SessionLocal() as db:
        events = db.scalars(
            select(EventLog).where(
                EventLog.event_type == "INTEGRATION_SKU_COSTS_QUERIED",
                EventLog.actor_id == integration_client["id"],
            )
        ).all()
    assert len(events) == 1
    assert events[0].payload["result_count"] == 0
    assert events[0].payload["error_count"] == 1


def test_cost_endpoints_require_supplier_cost_read_scope(
    client: TestClient,
    integration_client_factory: Callable[[list[str]], dict[str, Any]],
    cost_catalog: dict[str, Any],
) -> None:
    scoped_client = integration_client_factory(["supplier-skus:read"])
    headers = auth_headers(scoped_client)

    single_response = client.get(
        f"{BASE_PATH}/suppliers/{cost_catalog['first_supplier_id']}"
        f"/skus/{cost_catalog['active_sku_id']}/cost",
        headers=headers,
    )
    batch_response = client.post(
        f"{BASE_PATH}/sku-costs/query",
        headers=headers,
        json={
            "items": [
                {
                    "client_sku_id": "scope-test",
                    "supplier_id": cost_catalog["first_supplier_id"],
                    "supplier_sku_id": cost_catalog["active_sku_id"],
                }
            ]
        },
    )

    assert single_response.status_code == 403
    assert batch_response.status_code == 403
    with SessionLocal() as db:
        events = db.scalars(
            select(EventLog).where(
                EventLog.event_type == "INTEGRATION_SKU_COSTS_QUERIED",
                EventLog.actor_id == scoped_client["id"],
            )
        ).all()
    assert len(events) == 2
    assert {event.payload["endpoint"] for event in events} == {
        f"{BASE_PATH}/suppliers/{cost_catalog['first_supplier_id']}"
        f"/skus/{cost_catalog['active_sku_id']}/cost",
        f"{BASE_PATH}/sku-costs/query",
    }
    assert all(event.payload["result_count"] == 0 for event in events)
    assert all(event.payload["error_count"] == 1 for event in events)


@pytest.mark.parametrize(
    "payload",
    [
        {"items": []},
        {
            "items": [
                {
                    "client_sku_id": "",
                    "supplier_id": "supplier-id",
                    "supplier_sku_id": "supplier-sku-id",
                }
            ]
        },
        {
            "items": [
                {
                    "client_sku_id": str(index),
                    "supplier_id": "supplier-id",
                    "supplier_sku_id": "supplier-sku-id",
                }
                for index in range(501)
            ]
        },
    ],
    ids=["empty-items", "empty-client-sku-id", "more-than-500-items"],
)
def test_batch_cost_query_rejects_invalid_request_structure_with_400(
    client: TestClient,
    integration_client: dict[str, Any],
    payload: dict[str, Any],
) -> None:
    response = client.post(
        f"{BASE_PATH}/sku-costs/query",
        headers=auth_headers(integration_client),
        json=payload,
    )

    assert response.status_code == 400
    with SessionLocal() as db:
        events = db.scalars(
            select(EventLog).where(
                EventLog.event_type == "INTEGRATION_SKU_COSTS_QUERIED",
                EventLog.actor_id == integration_client["id"],
            )
        ).all()
    assert len(events) == 1
    assert events[0].payload["result_count"] == 0
    assert events[0].payload["error_count"] == 1


def test_identified_client_5xx_is_audited_in_an_independent_transaction(
    client: TestClient,
    integration_client: dict[str, Any],
    cost_catalog: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class EndpointFailure(RuntimeError):
        pass

    def fail_cost_resolution(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise EndpointFailure("forced endpoint failure")

    monkeypatch.setattr(
        integration_routes,
        "resolve_current_sku_cost",
        fail_cost_resolution,
    )

    with pytest.raises(EndpointFailure, match="forced endpoint failure"):
        client.get(
            f"{BASE_PATH}/suppliers/{cost_catalog['first_supplier_id']}"
            f"/skus/{cost_catalog['active_sku_id']}/cost",
            headers=auth_headers(integration_client),
        )

    with SessionLocal() as db:
        events = db.scalars(
            select(EventLog).where(
                EventLog.event_type == "INTEGRATION_SKU_COSTS_QUERIED",
                EventLog.actor_id == integration_client["id"],
            )
        ).all()
    assert len(events) == 1
    assert events[0].payload["result_count"] == 0
    assert events[0].payload["error_count"] == 1


def test_audit_write_failure_does_not_replace_successful_cost_response(
    client: TestClient,
    integration_client: dict[str, Any],
    cost_catalog: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_audit_write(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise RuntimeError("forced audit failure")

    monkeypatch.setattr(integration_routes, "record_event", fail_audit_write)

    response = client.get(
        f"{BASE_PATH}/suppliers/{cost_catalog['first_supplier_id']}"
        f"/skus/{cost_catalog['active_sku_id']}/cost",
        headers=auth_headers(integration_client),
    )

    assert response.status_code == 200
    assert response.json()["cost_price"] == "28.5000"


def test_audit_write_failure_does_not_replace_original_endpoint_exception(
    client: TestClient,
    integration_client: dict[str, Any],
    cost_catalog: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class EndpointFailure(RuntimeError):
        pass

    def fail_cost_resolution(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise EndpointFailure("original endpoint failure")

    def fail_audit_write(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise RuntimeError("replacement audit failure")

    monkeypatch.setattr(
        integration_routes,
        "resolve_current_sku_cost",
        fail_cost_resolution,
    )
    monkeypatch.setattr(integration_routes, "record_event", fail_audit_write)

    with pytest.raises(EndpointFailure, match="original endpoint failure"):
        client.get(
            f"{BASE_PATH}/suppliers/{cost_catalog['first_supplier_id']}"
            f"/skus/{cost_catalog['active_sku_id']}/cost",
            headers=auth_headers(integration_client),
        )


def test_unidentified_401_cost_requests_do_not_fabricate_audit_actors(
    client: TestClient,
    cost_catalog: dict[str, Any],
) -> None:
    path = (
        f"{BASE_PATH}/suppliers/{cost_catalog['first_supplier_id']}"
        f"/skus/{cost_catalog['active_sku_id']}/cost"
    )
    with SessionLocal() as db:
        before = db.scalar(
            select(func.count(EventLog.id)).where(
                EventLog.event_type == "INTEGRATION_SKU_COSTS_QUERIED"
            )
        )

    missing_token = client.get(path)
    unknown_token = client.get(
        path,
        headers={"Authorization": "Bearer m1i_unknown-token-value"},
    )

    assert missing_token.status_code == 401
    assert unknown_token.status_code == 401
    assert missing_token.headers["www-authenticate"] == "Bearer"
    assert unknown_token.headers["www-authenticate"] == "Bearer"
    with SessionLocal() as db:
        after = db.scalar(
            select(func.count(EventLog.id)).where(
                EventLog.event_type == "INTEGRATION_SKU_COSTS_QUERIED"
            )
        )
    assert after == before


def test_batch_cost_query_preserves_rows_isolates_errors_and_redacts_audit(
    client: TestClient,
    integration_client: dict[str, Any],
    cost_catalog: dict[str, Any],
) -> None:
    client_sku_ids = ["client-valid", "client-mode-b", "client-mismatch"]
    items = [
        {
            "client_sku_id": client_sku_ids[0],
            "supplier_id": cost_catalog["first_supplier_id"],
            "supplier_sku_id": cost_catalog["active_sku_id"],
        },
        {
            "client_sku_id": client_sku_ids[1],
            "supplier_id": cost_catalog["first_supplier_id"],
            "supplier_sku_id": cost_catalog["b2b_sku_id"],
        },
        {
            "client_sku_id": client_sku_ids[2],
            "supplier_id": cost_catalog["first_supplier_id"],
            "supplier_sku_id": cost_catalog["other_sku_id"],
        },
    ]

    response = client.post(
        f"{BASE_PATH}/sku-costs/query",
        headers=auth_headers(integration_client),
        json={"items": items},
    )

    assert response.status_code == 200
    results = response.json()["items"]
    assert [item["client_sku_id"] for item in results] == client_sku_ids
    assert results[0] == {
        "client_sku_id": client_sku_ids[0],
        "supplier_id": cost_catalog["first_supplier_id"],
        "supplier_sku_id": cost_catalog["active_sku_id"],
        "supplier_sku_code": cost_catalog["active_sku_code"],
        "cost_price": "28.5000",
        "currency": "CNY",
        "cost_updated_at": cost_catalog["cost_updated_at"].isoformat().replace(
            "+00:00", "Z"
        ),
        "status": "OK",
    }
    assert results[1] == {
        "client_sku_id": client_sku_ids[1],
        "supplier_id": cost_catalog["first_supplier_id"],
        "supplier_sku_id": cost_catalog["b2b_sku_id"],
        "status": "ERROR",
        "error_code": "NOT_SELF_PURCHASE",
        "message": "该货号所属品牌不是自营采购模式",
    }
    assert results[2] == {
        "client_sku_id": client_sku_ids[2],
        "supplier_id": cost_catalog["first_supplier_id"],
        "supplier_sku_id": cost_catalog["other_sku_id"],
        "status": "ERROR",
        "error_code": "SKU_SUPPLIER_MISMATCH",
        "message": "Supplier SKU 不属于该供应商",
    }

    with SessionLocal() as db:
        events = db.scalars(
            select(EventLog).where(
                EventLog.event_type == "INTEGRATION_SKU_COSTS_QUERIED",
                EventLog.actor_id == integration_client["id"],
            )
        ).all()
    assert len(events) == 1
    event = events[0]
    assert event.organization_id is None
    assert event.actor_type == "INTEGRATION_CLIENT"
    assert event.entity_type == "IntegrationClient"
    assert event.entity_id == integration_client["id"]
    assert event.payload["endpoint"] == f"{BASE_PATH}/sku-costs/query"
    assert event.payload["result_count"] == 1
    assert event.payload["error_count"] == 2
    persisted_payload = json.dumps(event.payload)
    assert all(client_sku_id not in persisted_payload for client_sku_id in client_sku_ids)
    assert "28.5000" not in persisted_payload
    assert integration_client["token"] not in persisted_payload


def test_resource_and_cost_routes_share_one_budget_and_cost_429_is_audited(
    client: TestClient,
    integration_client: dict[str, Any],
    integration_catalog: dict[str, Any],
    low_rate_limit: MutableRateLimitClock,
) -> None:
    del low_rate_limit
    headers = auth_headers(integration_client)

    suppliers_response = client.get(f"{BASE_PATH}/suppliers", headers=headers)
    brands_response = client.get(
        f"{BASE_PATH}/suppliers/{integration_catalog['first_supplier_id']}/brands",
        headers=headers,
    )
    request_id = "rate-limited-cost-request"
    cost_headers = {**headers, "X-Request-ID": request_id}
    cost_path = f"{BASE_PATH}/sku-costs/query"
    body_marker = "must-not-enter-the-audit"
    limited_response = client.post(
        cost_path,
        headers=cost_headers,
        json={
            "items": [
                {
                    "client_sku_id": body_marker,
                    "supplier_id": integration_catalog["first_supplier_id"],
                    "supplier_sku_id": "missing-sku",
                }
            ]
        },
    )

    assert suppliers_response.status_code == 200
    assert brands_response.status_code == 200
    assert limited_response.status_code == 429
    assert limited_response.json() == {"detail": "集成客户端请求频率超限"}
    assert limited_response.headers["retry-after"] == "60"
    assert limited_response.headers["content-security-policy"].startswith(
        "default-src 'self'"
    )
    assert limited_response.headers["x-frame-options"] == "DENY"
    assert limited_response.headers["x-content-type-options"] == "nosniff"
    assert limited_response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert limited_response.headers["permissions-policy"] == (
        "camera=(), microphone=(), geolocation=()"
    )
    with SessionLocal() as db:
        events = db.scalars(
            select(EventLog).where(
                EventLog.event_type == "INTEGRATION_SKU_COSTS_QUERIED",
                EventLog.actor_id == integration_client["id"],
            )
        ).all()
    assert len(events) == 1
    assert events[0].payload == {
        "request_id": request_id,
        "endpoint": cost_path,
        "result_count": 0,
        "error_count": 1,
    }
    persisted_payload = json.dumps(events[0].payload)
    assert integration_client["token"] not in persisted_payload
    assert body_marker not in persisted_payload


def test_production_trusted_host_rejects_cost_request_before_direct_rate_limit(
    client: TestClient,
    integration_client: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del client
    limiter = FixedWindowRateLimiter(
        max_requests=1,
        window_seconds=60,
        clock=MutableRateLimitClock(),
    )
    assert limiter.consume(str(integration_client["id"])) is None
    main_module = importlib.import_module("app.main")
    try:
        with monkeypatch.context() as production_context:
            production_context.setattr(
                integration_deps,
                "integration_rate_limiter",
                limiter,
            )
            production_context.setenv("APP_ENV", "production")
            production_context.setenv("ALLOWED_HOSTS", "trusted.example")
            get_settings.cache_clear()
            production_app = importlib.reload(main_module).app
            production_client = TestClient(
                production_app,
                base_url="http://untrusted.example",
                raise_server_exceptions=False,
            )
            try:
                response = production_client.post(
                    f"{BASE_PATH}/sku-costs/query",
                    headers=auth_headers(integration_client),
                    json={"items": []},
                )
            finally:
                production_client.close()
    finally:
        get_settings.cache_clear()
        restored_main_module = importlib.reload(main_module)

    assert response.status_code == 400
    assert "retry-after" not in response.headers
    assert restored_main_module.settings.app_env == "testing"


def test_clients_have_independent_budgets_and_windows_reopen_without_limiting_web(
    client: TestClient,
    integration_client: dict[str, Any],
    integration_client_factory: Callable[[list[str]], dict[str, Any]],
    low_rate_limit: MutableRateLimitClock,
) -> None:
    other_client = integration_client_factory(["suppliers:read"])
    first_headers = auth_headers(integration_client)
    other_headers = auth_headers(other_client)

    assert client.get(f"{BASE_PATH}/suppliers", headers=first_headers).status_code == 200
    assert client.get(f"{BASE_PATH}/suppliers", headers=first_headers).status_code == 200
    limited = client.get(f"{BASE_PATH}/suppliers", headers=first_headers)
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "60"

    assert client.get(f"{BASE_PATH}/suppliers", headers=other_headers).status_code == 200
    assert client.get(f"{BASE_PATH}/suppliers", headers=other_headers).status_code == 200
    for _ in range(4):
        assert client.get("/api/health").status_code == 200

    low_rate_limit.advance(60)
    assert client.get(f"{BASE_PATH}/suppliers", headers=first_headers).status_code == 200


def test_scope_failures_consume_budget_but_invalid_tokens_remain_actorless_401s(
    client: TestClient,
    integration_client_factory: Callable[[list[str]], dict[str, Any]],
    low_rate_limit: MutableRateLimitClock,
) -> None:
    del low_rate_limit
    scoped_client = integration_client_factory(["suppliers:read"])
    scoped_headers = auth_headers(scoped_client)
    cost_path = f"{BASE_PATH}/suppliers/any-supplier/skus/any-sku/cost"

    first_scope_failure = client.get(cost_path, headers=scoped_headers)
    second_scope_failure = client.get(cost_path, headers=scoped_headers)
    limited_resource = client.get(f"{BASE_PATH}/suppliers", headers=scoped_headers)

    assert first_scope_failure.status_code == 403
    assert second_scope_failure.status_code == 403
    assert limited_resource.status_code == 429
    assert limited_resource.headers["retry-after"] == "60"

    invalid_headers = {"Authorization": "Bearer m1i_unknown-token-value"}
    for _ in range(3):
        response = client.get(cost_path, headers=invalid_headers)
        assert response.status_code == 401
        assert "retry-after" not in response.headers

    with SessionLocal() as db:
        events = db.scalars(
            select(EventLog).where(
                EventLog.event_type == "INTEGRATION_SKU_COSTS_QUERIED",
                EventLog.actor_id == scoped_client["id"],
            )
        ).all()
    assert len(events) == 2
    assert all(event.payload["result_count"] == 0 for event in events)
    assert all(event.payload["error_count"] == 1 for event in events)
