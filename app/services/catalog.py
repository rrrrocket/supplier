from __future__ import annotations

from hashlib import md5

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import (
    Brand,
    CatalogStatus,
    Product,
    ProductVariant,
    SupplierBrandCooperation,
    SupplierSku,
)


def normalize_brand_name(value: str) -> str:
    return " ".join(value.strip().lower().split())


def resolve_brand(db: Session, name: str) -> Brand:
    normalized_name = normalize_brand_name(name)
    if not normalized_name:
        raise ValueError("brand name is required")

    brand = db.scalar(
        select(Brand).where(Brand.normalized_name == normalized_name)
    )
    if brand is not None:
        return brand

    digest = md5(
        normalized_name.encode("utf-8"), usedforsecurity=False
    ).hexdigest()[:10].upper()
    brand = Brand(
        code=f"BR-{digest}",
        name=name.strip(),
        normalized_name=normalized_name,
        aliases=[],
        status=CatalogStatus.ACTIVE.value,
    )
    db.add(brand)
    db.flush()
    return brand


def ensure_supplier_sku(
    db: Session,
    *,
    supplier_id: str,
    brand_id: str,
    product_id: str,
    variant_id: str | None,
    supplier_sku_code: str,
    manufacturer_part_number: str | None = None,
    barcode: str | None = None,
) -> SupplierSku:
    code = supplier_sku_code.strip()
    if not code:
        raise ValueError("supplier SKU code is required")

    product = db.get(Product, product_id)
    if product is None or product.created_by_organization_id != supplier_id:
        raise ValueError("product does not belong to supplier")
    if product.brand_id != brand_id:
        raise ValueError("product does not belong to brand")

    cooperation = db.scalar(
        select(SupplierBrandCooperation).where(
            SupplierBrandCooperation.supplier_id == supplier_id,
            SupplierBrandCooperation.brand_id == brand_id,
            SupplierBrandCooperation.status == CatalogStatus.ACTIVE.value,
        )
    )
    if cooperation is None:
        raise ValueError("brand is not assigned to supplier")

    if variant_id is not None:
        variant = db.get(ProductVariant, variant_id)
        if variant is None or variant.product_id != product_id:
            raise ValueError("variant does not belong to product")

    supplier_sku = db.scalar(
        select(SupplierSku).where(
            SupplierSku.supplier_id == supplier_id,
            SupplierSku.supplier_sku_code == code,
        )
    )
    if supplier_sku is not None:
        identity = (
            supplier_sku.brand_id,
            supplier_sku.product_id,
            supplier_sku.variant_id,
        )
        if identity != (brand_id, product_id, variant_id):
            raise ValueError("supplier SKU code is already bound")
        for field, value in (
            ("manufacturer_part_number", manufacturer_part_number),
            ("barcode", barcode),
        ):
            current = getattr(supplier_sku, field)
            if value is not None and current not in (None, value):
                raise ValueError(f"supplier SKU {field} conflicts")
            if current is None and value is not None:
                setattr(supplier_sku, field, value)
        return supplier_sku

    supplier_sku = SupplierSku(
        supplier_id=supplier_id,
        brand_id=brand_id,
        product_id=product_id,
        variant_id=variant_id,
        supplier_sku_code=code,
        manufacturer_part_number=manufacturer_part_number,
        barcode=barcode,
        status=CatalogStatus.ACTIVE.value,
    )
    db.add(supplier_sku)
    db.flush()
    return supplier_sku
