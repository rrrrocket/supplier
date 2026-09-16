from __future__ import annotations

from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.entities import (
    Brand,
    CatalogStatus,
    CommercialMode,
    EventLog,
    Organization,
    OrganizationType,
    Product,
    SupplierBrandCooperation,
    SupplierSku,
    User,
)


def test_ensure_supplier_sku_rejects_product_owned_by_another_supplier(
    client: TestClient,
) -> None:
    del client
    from app.services.catalog import ensure_supplier_sku

    suffix = uuid4().hex[:8]
    with SessionLocal() as db:
        supplier = db.scalar(
            select(Organization).where(Organization.code == "TEST-SUPPLIER")
        )
        brand = db.scalar(select(Brand).where(Brand.code == "TEST-BRAND"))
        assert supplier is not None
        assert brand is not None

        other_supplier = Organization(
            code=f"OTHER-{suffix}",
            name=f"其他供应商-{suffix}",
            organization_type=OrganizationType.SUPPLIER.value,
        )
        db.add(other_supplier)
        db.flush()
        product = Product(
            created_by_organization_id=other_supplier.id,
            brand_id=brand.id,
            name=f"跨租户商品-{suffix}",
            category="测试类目",
        )
        db.add(product)
        db.flush()

        with pytest.raises(ValueError, match="product does not belong to supplier"):
            ensure_supplier_sku(
                db,
                supplier_id=supplier.id,
                brand_id=brand.id,
                product_id=product.id,
                variant_id=None,
                supplier_sku_code=f"CROSS-{suffix}",
            )


def test_ensure_supplier_sku_rejects_brand_not_assigned_to_supplier(
    client: TestClient,
) -> None:
    del client
    from app.services.catalog import ensure_supplier_sku

    suffix = uuid4().hex[:8]
    with SessionLocal() as db:
        supplier = db.scalar(
            select(Organization).where(Organization.code == "TEST-SUPPLIER")
        )
        assert supplier is not None

        other_supplier = Organization(
            code=f"BRAND-OWNER-{suffix}",
            name=f"品牌合作供应商-{suffix}",
            organization_type=OrganizationType.SUPPLIER.value,
        )
        brand = Brand(
            code=f"UNASSIGNED-{suffix}",
            name=f"未分配品牌-{suffix}",
            normalized_name=f"unassigned-{suffix}",
            aliases=[],
            status=CatalogStatus.ACTIVE.value,
        )
        db.add_all([other_supplier, brand])
        db.flush()
        db.add(
            SupplierBrandCooperation(
                supplier_id=other_supplier.id,
                brand_id=brand.id,
                commercial_mode=CommercialMode.SELF_PURCHASE.value,
                status=CatalogStatus.ACTIVE.value,
            )
        )
        product = Product(
            created_by_organization_id=supplier.id,
            brand_id=brand.id,
            name=f"未分配品牌商品-{suffix}",
            category="测试类目",
        )
        db.add(product)
        db.flush()

        with pytest.raises(ValueError, match="brand is not assigned to supplier"):
            ensure_supplier_sku(
                db,
                supplier_id=supplier.id,
                brand_id=brand.id,
                product_id=product.id,
                variant_id=None,
                supplier_sku_code=f"UNASSIGNED-{suffix}",
            )


def test_replace_active_cooperation_is_idempotent_and_keeps_sku_identity(
    client: TestClient,
) -> None:
    del client
    from app.services.catalog import replace_active_cooperation

    suffix = uuid4().hex[:8]
    with SessionLocal() as db:
        supplier = db.scalar(
            select(Organization).where(Organization.code == "TEST-SUPPLIER")
        )
        admin = db.scalar(
            select(User).where(User.email == "admin-test@example.com")
        )
        assert supplier is not None
        assert admin is not None

        brand = Brand(
            code=f"SERVICE-{suffix}",
            name=f"服务测试品牌 {suffix}",
            normalized_name=f"服务测试品牌 {suffix}",
            aliases=[],
            status=CatalogStatus.ACTIVE.value,
        )
        db.add(brand)
        db.flush()
        product = Product(
            created_by_organization_id=supplier.id,
            brand_id=brand.id,
            name=f"服务测试商品 {suffix}",
            category="测试类目",
        )
        db.add(product)
        db.flush()
        current = SupplierBrandCooperation(
            supplier_id=supplier.id,
            brand_id=brand.id,
            commercial_mode=CommercialMode.SELF_PURCHASE.value,
            status=CatalogStatus.ACTIVE.value,
        )
        supplier_sku = SupplierSku(
            supplier_id=supplier.id,
            brand_id=brand.id,
            product_id=product.id,
            supplier_sku_code=f"SERVICE-SKU-{suffix}",
            status=CatalogStatus.ACTIVE.value,
        )
        db.add_all([current, supplier_sku])
        db.flush()
        original_sku_id = supplier_sku.id

        unchanged = replace_active_cooperation(
            db,
            supplier_id=supplier.id,
            brand_id=brand.id,
            commercial_mode=CommercialMode.SELF_PURCHASE.value,
            actor_id=admin.id,
        )
        db.flush()
        assert unchanged.id == current.id
        assert db.scalars(
            select(EventLog).where(
                EventLog.event_type == "SUPPLIER_BRAND_COOPERATION_CHANGED",
                EventLog.organization_id == supplier.id,
                EventLog.payload["brand_id"].as_string() == brand.id,
            )
        ).all() == []

        replacement = replace_active_cooperation(
            db,
            supplier_id=supplier.id,
            brand_id=brand.id,
            commercial_mode=CommercialMode.B2B.value,
            actor_id=admin.id,
        )
        db.flush()

        assert replacement.id != current.id
        assert current.status == CatalogStatus.INACTIVE.value
        assert replacement.status == CatalogStatus.ACTIVE.value
        assert replacement.commercial_mode == CommercialMode.B2B.value
        assert db.get(SupplierSku, original_sku_id).id == original_sku_id
        event = db.scalar(
            select(EventLog).where(
                EventLog.event_type == "SUPPLIER_BRAND_COOPERATION_CHANGED",
                EventLog.entity_id == replacement.id,
            )
        )
        assert event is not None
        assert event.actor_id == admin.id
        assert event.payload["previous_mode"] == CommercialMode.SELF_PURCHASE.value
        assert event.payload["commercial_mode"] == CommercialMode.B2B.value


def test_ensure_supplier_sku_concurrently_returns_one_stable_identity(
    client: TestClient,
) -> None:
    del client
    from app.services.catalog import ensure_supplier_sku

    suffix = uuid4().hex[:8]
    with SessionLocal() as db:
        supplier = db.scalar(
            select(Organization).where(Organization.code == "TEST-SUPPLIER")
        )
        brand = db.scalar(select(Brand).where(Brand.code == "TEST-BRAND"))
        assert supplier is not None and brand is not None
        product = Product(
            created_by_organization_id=supplier.id,
            brand_id=brand.id,
            name=f"并发 SKU 商品-{suffix}",
            category="测试类目",
        )
        db.add(product)
        db.commit()
        supplier_id, brand_id, product_id = supplier.id, brand.id, product.id

    barrier = Barrier(2)

    def create() -> str:
        with SessionLocal() as db:
            barrier.wait(timeout=5)
            sku = ensure_supplier_sku(
                db,
                supplier_id=supplier_id,
                brand_id=brand_id,
                product_id=product_id,
                variant_id=None,
                supplier_sku_code=f"RACE-{suffix}",
            )
            db.commit()
            return sku.id

    with ThreadPoolExecutor(max_workers=2) as executor:
        sku_ids = list(executor.map(lambda _: create(), range(2)))

    assert sku_ids[0] == sku_ids[1]
    with SessionLocal() as db:
        matching_skus = db.scalars(
            select(SupplierSku).where(
                SupplierSku.supplier_id == supplier_id,
                SupplierSku.supplier_sku_code == f"RACE-{suffix}",
            )
        ).all()
        assert len(matching_skus) == 1


def test_first_cooperation_writes_are_serialized_for_supplier_and_brand(
    client: TestClient,
) -> None:
    del client
    from app.services.catalog import replace_active_cooperation

    suffix = uuid4().hex[:8]
    with SessionLocal() as db:
        supplier = db.scalar(
            select(Organization).where(Organization.code == "TEST-SUPPLIER")
        )
        admin = db.scalar(select(User).where(User.email == "admin-test@example.com"))
        assert supplier is not None and admin is not None
        brand = Brand(
            code=f"RACE-BRAND-{suffix}",
            name=f"并发合作品牌-{suffix}",
            normalized_name=f"race brand {suffix}",
            aliases=[],
            status=CatalogStatus.ACTIVE.value,
        )
        db.add(brand)
        db.commit()
        supplier_id, brand_id, actor_id = supplier.id, brand.id, admin.id

    barrier = Barrier(2)

    def replace(mode: str) -> str:
        with SessionLocal() as db:
            barrier.wait(timeout=5)
            cooperation = replace_active_cooperation(
                db,
                supplier_id=supplier_id,
                brand_id=brand_id,
                commercial_mode=mode,
                actor_id=actor_id,
            )
            db.commit()
            return cooperation.id

    with ThreadPoolExecutor(max_workers=2) as executor:
        ids = list(
            executor.map(
                replace,
                [CommercialMode.B2B.value, CommercialMode.JOINT_OPERATION.value],
            )
        )

    assert len(ids) == 2
    with SessionLocal() as db:
        active = db.scalars(
            select(SupplierBrandCooperation).where(
                SupplierBrandCooperation.supplier_id == supplier_id,
                SupplierBrandCooperation.brand_id == brand_id,
                SupplierBrandCooperation.status == CatalogStatus.ACTIVE.value,
            )
        ).all()
        assert len(active) == 1


def test_import_brand_auto_link_is_safe_under_concurrent_writes(
    client: TestClient,
) -> None:
    del client
    from app.services.catalog import resolve_import_brand

    suffix = uuid4().hex[:8]
    brand_name = f"并发导入品牌-{suffix}"
    with SessionLocal() as db:
        supplier = db.scalar(
            select(Organization).where(Organization.code == "TEST-SUPPLIER")
        )
        assert supplier is not None
        other_supplier = Organization(
            code=f"RACE-SUPPLIER-{suffix}",
            name=f"并发供应商-{suffix}",
            organization_type=OrganizationType.SUPPLIER.value,
        )
        db.add(other_supplier)
        db.commit()
        supplier_ids = [supplier.id, other_supplier.id]

    barrier = Barrier(2)

    def create(supplier_id: str) -> str:
        with SessionLocal() as db:
            barrier.wait(timeout=5)
            brand = resolve_import_brand(db, supplier_id, brand_name)
            db.commit()
            return brand.id

    with ThreadPoolExecutor(max_workers=2) as executor:
        brand_ids = list(executor.map(create, supplier_ids))

    assert brand_ids[0] == brand_ids[1]
    with SessionLocal() as db:
        active = db.scalars(
            select(SupplierBrandCooperation).where(
                SupplierBrandCooperation.supplier_id.in_(supplier_ids),
                SupplierBrandCooperation.brand_id == brand_ids[0],
                SupplierBrandCooperation.status == CatalogStatus.ACTIVE.value,
            )
        ).all()
        assert len(active) == 2
        assert {item.supplier_id for item in active} == set(supplier_ids)
        assert all(item.commercial_mode == CommercialMode.SELF_PURCHASE.value for item in active)
