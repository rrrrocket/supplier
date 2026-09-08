from __future__ import annotations

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
            brand=brand.name,
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
            brand=brand.name,
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
