from __future__ import annotations

import base64
import json
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.entities import (
    Brand,
    CatalogStatus,
    CommercialMode,
    Organization,
    OrganizationType,
    Product,
    SupplierBrandCooperation,
    SupplierProfile,
    SupplierSku,
    SupplierStatus,
)
from app.services.integration_pagination import decode_cursor, encode_cursor


BASE_PATH = "/api/integrations/v1"


def auth_headers(integration_client: dict[str, Any]) -> dict[str, str]:
    return {"Authorization": f"Bearer {integration_client['token']}"}


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
            brand=active_brand.name,
            brand_id=active_brand.id,
            name=f"集成商品 A {suffix}",
            model="MODEL-A",
            category="集成测试",
            created_at=old_time,
            updated_at=page_time,
        )
        inactive_product = Product(
            created_by_organization_id=first_supplier.id,
            brand=inactive_cooperation_brand.name,
            brand_id=inactive_cooperation_brand.id,
            name=f"失效合作商品 {suffix}",
            model=None,
            category="集成测试",
            created_at=old_time,
            updated_at=page_time,
        )
        other_product = Product(
            created_by_organization_id=second_supplier.id,
            brand=other_supplier_brand.name,
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
