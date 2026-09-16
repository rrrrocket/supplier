from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from hashlib import md5

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.base import new_id, utcnow

from app.models.entities import (
    Brand,
    CatalogStatus,
    CommercialMode,
    OfferStatus,
    Organization,
    OrganizationType,
    Product,
    ProductVariant,
    SupplierBrandCooperation,
    SupplierOffer,
    SupplierProfile,
    SupplierSku,
    SupplierStatus,
)
from app.schemas.integration import SkuCostErrorCode
from app.services.events import record_event


@dataclass(frozen=True)
class CurrentSkuCost:
    supplier_id: str
    supplier_sku_id: str
    supplier_sku_code: str
    cost_price: Decimal
    currency: str
    cost_updated_at: datetime


class SkuCostError(Exception):
    def __init__(self, code: SkuCostErrorCode, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


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
    identifier = new_id()
    timestamp = utcnow()
    inserted_id = db.scalar(
        insert(Brand)
        .values(
            id=identifier,
            code=f"BR-{digest}",
            name=name.strip(),
            normalized_name=normalized_name,
            aliases=[],
            status=CatalogStatus.ACTIVE.value,
            created_at=timestamp,
            updated_at=timestamp,
        )
        .on_conflict_do_nothing(index_elements=[Brand.normalized_name])
        .returning(Brand.id)
    )
    if inserted_id is not None:
        created = db.get(Brand, inserted_id)
        if created is not None:
            return created
    existing = db.scalar(
        select(Brand).where(Brand.normalized_name == normalized_name)
    )
    if existing is None:
        raise RuntimeError("brand could not be resolved after concurrent insert")
    return existing


def resolve_import_brand(db: Session, supplier_id: str, name: str) -> Brand:
    """Resolve a brand and create a pending supplier link under one supplier lock."""
    supplier = db.execute(
        select(Organization.id)
        .where(Organization.id == supplier_id)
        .with_for_update()
    ).one_or_none()
    if supplier is None:
        raise ValueError("supplier does not exist")

    brand = resolve_brand(db, name)
    cooperation = db.scalar(
        select(SupplierBrandCooperation).where(
            SupplierBrandCooperation.supplier_id == supplier_id,
            SupplierBrandCooperation.brand_id == brand.id,
            SupplierBrandCooperation.status == CatalogStatus.ACTIVE.value,
        )
    )
    if cooperation is None:
        db.add(
            SupplierBrandCooperation(
                supplier_id=supplier_id,
                brand_id=brand.id,
                commercial_mode=CommercialMode.SELF_PURCHASE.value,
                status=CatalogStatus.ACTIVE.value,
            )
        )
        db.flush()
    return brand


def replace_active_cooperation(
    db: Session,
    supplier_id: str,
    brand_id: str,
    commercial_mode: str,
    actor_id: str,
) -> SupplierBrandCooperation:
    supplier = db.execute(
        select(Organization.id, Organization.organization_type)
        .where(Organization.id == supplier_id)
        .with_for_update()
    ).one_or_none()
    if supplier is None or supplier.organization_type != OrganizationType.SUPPLIER.value:
        raise ValueError("supplier does not exist")
    current = db.scalar(
        select(SupplierBrandCooperation)
        .where(
            SupplierBrandCooperation.supplier_id == supplier_id,
            SupplierBrandCooperation.brand_id == brand_id,
            SupplierBrandCooperation.status == CatalogStatus.ACTIVE.value,
        )
        .with_for_update()
    )
    if current is not None and current.commercial_mode == commercial_mode:
        return current

    previous_mode = current.commercial_mode if current is not None else None
    if current is not None:
        current.status = CatalogStatus.INACTIVE.value

    replacement = SupplierBrandCooperation(
        supplier_id=supplier_id,
        brand_id=brand_id,
        commercial_mode=commercial_mode,
        status=CatalogStatus.ACTIVE.value,
    )
    db.add(replacement)
    db.flush()
    record_event(
        db,
        event_type="SUPPLIER_BRAND_COOPERATION_CHANGED",
        entity_type="SupplierBrandCooperation",
        entity_id=replacement.id,
        organization_id=supplier_id,
        actor_type="USER",
        actor_id=actor_id,
        payload={
            "brand_id": brand_id,
            "previous_mode": previous_mode,
            "commercial_mode": commercial_mode,
        },
    )
    return replacement


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

    identifier = new_id()
    timestamp = utcnow()
    inserted_id = db.scalar(
        insert(SupplierSku)
        .values(
            id=identifier,
            supplier_id=supplier_id,
            brand_id=brand_id,
            product_id=product_id,
            variant_id=variant_id,
            supplier_sku_code=code,
            manufacturer_part_number=manufacturer_part_number,
            barcode=barcode,
            status=CatalogStatus.ACTIVE.value,
            created_at=timestamp,
            updated_at=timestamp,
        )
        .on_conflict_do_nothing(constraint="uq_supplier_brand_sku_code")
        .returning(SupplierSku.id)
    )
    supplier_sku = db.get(SupplierSku, inserted_id) if inserted_id else db.scalar(
        select(SupplierSku).where(
            SupplierSku.supplier_id == supplier_id,
            SupplierSku.brand_id == brand_id,
            SupplierSku.supplier_sku_code == code,
        )
    )
    assert supplier_sku is not None
    identity = (supplier_sku.brand_id, supplier_sku.product_id, supplier_sku.variant_id)
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


def resolve_current_sku_cost(
    db: Session,
    *,
    supplier_id: str,
    supplier_sku_id: str,
    scope_sku_to_supplier: bool = False,
) -> CurrentSkuCost:
    supplier = db.get(Organization, supplier_id)
    if (
        supplier is None
        or supplier.organization_type != OrganizationType.SUPPLIER.value
    ):
        raise SkuCostError(SkuCostErrorCode.SUPPLIER_NOT_FOUND, "供应商不存在")
    if not supplier.is_active:
        raise SkuCostError(SkuCostErrorCode.SUPPLIER_INACTIVE, "供应商已停用")
    profile = db.scalar(
        select(SupplierProfile).where(
            SupplierProfile.organization_id == supplier_id,
        )
    )
    if profile is None or profile.status != SupplierStatus.APPROVED.value:
        raise SkuCostError(SkuCostErrorCode.SUPPLIER_INACTIVE, "供应商已停用")

    sku_conditions = [SupplierSku.id == supplier_sku_id]
    if scope_sku_to_supplier:
        sku_conditions.append(SupplierSku.supplier_id == supplier_id)
    supplier_sku = db.scalar(select(SupplierSku).where(*sku_conditions))
    if supplier_sku is None:
        raise SkuCostError(SkuCostErrorCode.SKU_NOT_FOUND, "Supplier SKU 不存在")
    if supplier_sku.supplier_id != supplier_id:
        raise SkuCostError(
            SkuCostErrorCode.SKU_SUPPLIER_MISMATCH,
            "Supplier SKU 不属于该供应商",
        )
    if supplier_sku.status != CatalogStatus.ACTIVE.value:
        raise SkuCostError(SkuCostErrorCode.SKU_INACTIVE, "Supplier SKU 已停用")
    product = db.get(Product, supplier_sku.product_id)
    if (
        product is None
        or product.created_by_organization_id != supplier_id
        or product.brand_id != supplier_sku.brand_id
    ):
        raise SkuCostError(
            SkuCostErrorCode.SKU_SUPPLIER_MISMATCH,
            "Supplier SKU 商品归属不一致",
        )
    if supplier_sku.variant_id is not None:
        variant = db.get(ProductVariant, supplier_sku.variant_id)
        if variant is None or variant.product_id != product.id:
            raise SkuCostError(
                SkuCostErrorCode.SKU_SUPPLIER_MISMATCH,
                "Supplier SKU 规格归属不一致",
            )

    cooperation = db.scalar(
        select(SupplierBrandCooperation).where(
            SupplierBrandCooperation.supplier_id == supplier_id,
            SupplierBrandCooperation.brand_id == supplier_sku.brand_id,
            SupplierBrandCooperation.status == CatalogStatus.ACTIVE.value,
        )
    )
    if cooperation is None:
        raise SkuCostError(
            SkuCostErrorCode.BRAND_COOPERATION_INACTIVE,
            "品牌合作关系未启用",
        )
    if cooperation.commercial_mode != CommercialMode.SELF_PURCHASE.value:
        raise SkuCostError(
            SkuCostErrorCode.NOT_SELF_PURCHASE,
            "该货号所属品牌不是自营采购模式",
        )

    offer = db.scalar(
        select(SupplierOffer).where(
            SupplierOffer.supplier_sku_id == supplier_sku_id,
            SupplierOffer.organization_id == supplier_id,
            SupplierOffer.product_id == supplier_sku.product_id,
            SupplierOffer.variant_id.is_not_distinct_from(supplier_sku.variant_id),
            SupplierOffer.status == OfferStatus.ACTIVE.value,
        )
    )
    if offer is None or offer.price is None:
        raise SkuCostError(SkuCostErrorCode.COST_PRICE_MISSING, "当前成本价不存在")

    return CurrentSkuCost(
        supplier_id=supplier_id,
        supplier_sku_id=supplier_sku_id,
        supplier_sku_code=supplier_sku.supplier_sku_code,
        cost_price=offer.price,
        currency=offer.currency,
        cost_updated_at=offer.updated_at,
    )
