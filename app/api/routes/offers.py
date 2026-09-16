from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import DbSession, SupplierUser
from app.models.entities import (
    Brand,
    CatalogStatus,
    InventorySnapshot,
    Product,
    SupplierBrandCooperation,
    SupplierOffer,
    SupplierSku,
)
from app.schemas.product import OfferCreate, OfferPage, OfferUpdate, OfferView
from app.services.catalog import ensure_supplier_sku
from app.services.events import record_event
from app.services.list_pagination import decode_list_cursor, encode_list_cursor


router = APIRouter(prefix="/offers", tags=["商品报价"])


def offer_view(
    offer: SupplierOffer,
    product: Product,
    brand: Brand,
    supplier_sku: SupplierSku,
    commercial_mode: str | None,
) -> OfferView:
    return OfferView(
        id=offer.id,
        supplier_sku_id=supplier_sku.id,
        supplier_sku_code=supplier_sku.supplier_sku_code,
        product_id=offer.product_id,
        product_name=product.name,
        brand_id=brand.id,
        brand=brand.name,
        commercial_mode=commercial_mode,
        model=product.model,
        category=product.category,
        price=offer.price,
        currency=offer.currency,
        moq=offer.moq,
        stock_qty=offer.stock_qty,
        lead_time_days=offer.lead_time_days,
        fulfillment_mode=offer.fulfillment_mode,
        valid_until=offer.valid_until,
        status=offer.status,
        notes=offer.notes,
        updated_at=offer.updated_at,
    )


@router.get("", response_model=list[OfferView])
def list_offers(
    db: DbSession,
    user: SupplierUser,
    q: str | None = Query(default=None, max_length=240),
    brand: str | None = Query(default=None, max_length=160),
    offer_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> list[OfferView]:
    stmt = (
        select(
            SupplierOffer,
            Product,
            Brand,
            SupplierSku,
            SupplierBrandCooperation.commercial_mode,
        )
        .join(Product, Product.id == SupplierOffer.product_id)
        .join(Brand, Brand.id == Product.brand_id)
        .join(SupplierSku, SupplierSku.id == SupplierOffer.supplier_sku_id)
        .outerjoin(
            SupplierBrandCooperation,
            (SupplierBrandCooperation.supplier_id == SupplierOffer.organization_id)
            & (SupplierBrandCooperation.brand_id == Product.brand_id)
            & (SupplierBrandCooperation.status == CatalogStatus.ACTIVE.value),
        )
        .where(SupplierOffer.organization_id == user.organization_id)
    )
    if q:
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                SupplierSku.supplier_sku_code.ilike(pattern),
                Product.name.ilike(pattern),
                Brand.name.ilike(pattern),
                Product.model.ilike(pattern),
            )
        )
    if offer_status:
        stmt = stmt.where(SupplierOffer.status == offer_status)
    if brand:
        stmt = stmt.where(Brand.name == brand.strip())
    stmt = (
        stmt.order_by(SupplierOffer.updated_at.desc(), SupplierOffer.id.desc())
        .offset(offset)
        .limit(limit)
    )

    return [
        offer_view(offer, product, brand, supplier_sku, commercial_mode)
        for offer, product, brand, supplier_sku, commercial_mode in db.execute(stmt).all()
    ]


@router.get("/page", response_model=OfferPage)
def list_offers_page(
    db: DbSession,
    user: SupplierUser,
    q: str | None = Query(default=None, max_length=240),
    brand: str | None = Query(default=None, max_length=160),
    offer_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=500, ge=1, le=500),
    cursor: str | None = Query(default=None),
) -> OfferPage:
    filters = {
        "organization_id": user.organization_id,
        "q": q.strip() if q else None,
        "brand": brand.strip() if brand else None,
        "status": offer_status,
    }
    after_id = decode_list_cursor(cursor, "offers", filters) if cursor else None
    stmt = (
        select(
            SupplierOffer,
            Product,
            Brand,
            SupplierSku,
            SupplierBrandCooperation.commercial_mode,
        )
        .join(Product, Product.id == SupplierOffer.product_id)
        .join(Brand, Brand.id == Product.brand_id)
        .join(SupplierSku, SupplierSku.id == SupplierOffer.supplier_sku_id)
        .outerjoin(
            SupplierBrandCooperation,
            (SupplierBrandCooperation.supplier_id == SupplierOffer.organization_id)
            & (SupplierBrandCooperation.brand_id == Product.brand_id)
            & (SupplierBrandCooperation.status == CatalogStatus.ACTIVE.value),
        )
        .where(SupplierOffer.organization_id == user.organization_id)
    )
    if filters["q"]:
        pattern = f"%{filters['q']}%"
        stmt = stmt.where(
            or_(
                SupplierSku.supplier_sku_code.ilike(pattern),
                Product.name.ilike(pattern),
                Brand.name.ilike(pattern),
                Product.model.ilike(pattern),
            )
        )
    if offer_status:
        stmt = stmt.where(SupplierOffer.status == offer_status)
    if filters["brand"]:
        stmt = stmt.where(Brand.name == filters["brand"])
    if after_id:
        stmt = stmt.where(SupplierOffer.id > after_id)
    rows = db.execute(stmt.order_by(SupplierOffer.id).limit(limit + 1)).all()
    page = rows[:limit]
    next_cursor = (
        encode_list_cursor("offers", page[-1][0].id, filters)
        if len(rows) > limit else None
    )
    return OfferPage(
        items=[
            offer_view(offer, product, item_brand, sku, mode)
            for offer, product, item_brand, sku, mode in page
        ],
        next_cursor=next_cursor,
    )


@router.get("/brands", response_model=list[str])
def list_offer_brands(db: DbSession, user: SupplierUser) -> list[str]:
    return list(
        db.scalars(
            select(Brand.name)
            .select_from(SupplierOffer)
            .join(Product, Product.id == SupplierOffer.product_id)
            .join(Brand, Brand.id == Product.brand_id)
            .where(
                SupplierOffer.organization_id == user.organization_id,
            )
            .distinct()
            .order_by(Brand.name)
        ).all()
    )


@router.delete("/brand")
def delete_brand_offers(
    db: DbSession,
    user: SupplierUser,
    brand: str = Query(min_length=1, max_length=160),
) -> dict[str, int | str]:
    """Delete all supplier-owned data for one brand dimension."""
    brand_name = brand.strip()
    if not brand_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="品牌不能为空",
        )
    product_filter = (
        select(Product.id)
        .join(Brand, Brand.id == Product.brand_id)
        .where(
            Product.created_by_organization_id == user.organization_id,
            Brand.name == brand_name,
        )
    )
    offer_filter = select(SupplierOffer.id).where(
        SupplierOffer.organization_id == user.organization_id,
        SupplierOffer.product_id.in_(product_filter),
    )
    offer_count = db.scalar(
        select(func.count()).select_from(SupplierOffer).where(SupplierOffer.id.in_(offer_filter))
    ) or 0
    product_ids = list(db.scalars(product_filter).all())
    sku_filter = select(SupplierSku.id).where(
        SupplierSku.supplier_id == user.organization_id,
        SupplierSku.product_id.in_(product_ids),
    ) if product_ids else None
    sku_count = db.scalar(
        select(func.count()).select_from(SupplierSku).where(SupplierSku.id.in_(sku_filter))
    ) if sku_filter is not None else 0
    if offer_count:
        db.execute(
            delete(InventorySnapshot).where(
                InventorySnapshot.offer_id.in_(offer_filter)
            )
        )
        db.execute(
            delete(SupplierOffer).where(
                SupplierOffer.id.in_(offer_filter)
            )
        )
    if sku_filter is not None and sku_count:
        db.execute(delete(SupplierSku).where(SupplierSku.id.in_(sku_filter)))
    product_count = len(product_ids)
    if product_ids:
        db.execute(delete(Product).where(Product.id.in_(product_ids)))
    cooperation_filter = (
        select(SupplierBrandCooperation.id)
        .join(Brand, Brand.id == SupplierBrandCooperation.brand_id)
        .where(
            SupplierBrandCooperation.supplier_id == user.organization_id,
            Brand.name == brand_name,
        )
    )
    cooperation_count = db.scalar(
        select(func.count()).select_from(SupplierBrandCooperation).where(
            SupplierBrandCooperation.id.in_(cooperation_filter)
        )
    ) or 0
    if cooperation_count:
        db.execute(delete(SupplierBrandCooperation).where(SupplierBrandCooperation.id.in_(cooperation_filter)))
    record_event(
        db,
        event_type="OFFERS_DELETED_BY_BRAND",
        entity_type="SupplierOfferBrand",
        entity_id=None,
        organization_id=user.organization_id,
        actor_type="USER",
        actor_id=user.id,
        payload={
            "brand": brand_name,
            "deleted_count": int(offer_count),
            "deleted_products": product_count,
            "deleted_supplier_skus": int(sku_count),
            "deleted_cooperations": int(cooperation_count),
        },
    )
    db.commit()
    return {
        "brand": brand_name,
        "deleted_count": int(offer_count),
        "deleted_products": product_count,
        "deleted_supplier_skus": int(sku_count),
        "deleted_cooperations": int(cooperation_count),
    }


@router.post("", response_model=OfferView, status_code=status.HTTP_201_CREATED)
def create_offer(
    payload: OfferCreate,
    db: DbSession,
    user: SupplierUser,
) -> OfferView:
    product = db.scalar(
        select(Product).where(
            Product.id == payload.product_id,
            Product.created_by_organization_id == user.organization_id,
        )
    )
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="商品不存在")
    try:
        supplier_sku = ensure_supplier_sku(
            db,
            supplier_id=user.organization_id,
            brand_id=product.brand_id,
            product_id=product.id,
            variant_id=None,
            supplier_sku_code=payload.supplier_sku_code,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    brand = db.get(Brand, product.brand_id)
    if brand is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="product does not belong to brand",
        )
    cooperation = db.scalar(
        select(SupplierBrandCooperation).where(
            SupplierBrandCooperation.supplier_id == user.organization_id,
            SupplierBrandCooperation.brand_id == brand.id,
            SupplierBrandCooperation.status == CatalogStatus.ACTIVE.value,
        )
    )
    if cooperation is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="brand is not assigned to supplier",
        )

    offer = SupplierOffer(
        organization_id=user.organization_id,
        product_id=product.id,
        supplier_sku_id=supplier_sku.id,
        price=payload.price,
        currency=payload.currency,
        moq=payload.moq,
        stock_qty=payload.stock_qty,
        lead_time_days=payload.lead_time_days,
        fulfillment_mode=payload.fulfillment_mode,
        valid_until=payload.valid_until,
        status=payload.status,
        notes=(payload.notes or "").strip() or None,
    )
    db.add(offer)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="供应商SKU已存在",
        ) from exc

    db.add(
        InventorySnapshot(
            offer_id=offer.id,
            quantity=offer.stock_qty,
            source="MANUAL",
        )
    )
    record_event(
        db,
        event_type="OFFER_CREATED",
        entity_type="SupplierOffer",
        entity_id=offer.id,
        organization_id=user.organization_id,
        actor_type="USER",
        actor_id=user.id,
        payload={
            "supplier_sku_code": supplier_sku.supplier_sku_code,
            "product_name": product.name,
        },
    )
    db.commit()
    db.refresh(offer)
    return offer_view(
        offer,
        product,
        brand,
        supplier_sku,
        cooperation.commercial_mode,
    )


@router.patch("/{offer_id}", response_model=OfferView)
def update_offer(
    offer_id: str,
    payload: OfferUpdate,
    db: DbSession,
    user: SupplierUser,
) -> OfferView:
    row = db.execute(
        select(
            SupplierOffer,
            Product,
            Brand,
            SupplierSku,
            SupplierBrandCooperation.commercial_mode,
        )
        .join(Product, Product.id == SupplierOffer.product_id)
        .join(Brand, Brand.id == Product.brand_id)
        .join(SupplierSku, SupplierSku.id == SupplierOffer.supplier_sku_id)
        .outerjoin(
            SupplierBrandCooperation,
            (SupplierBrandCooperation.supplier_id == SupplierOffer.organization_id)
            & (SupplierBrandCooperation.brand_id == Product.brand_id)
            & (SupplierBrandCooperation.status == CatalogStatus.ACTIVE.value),
        )
        .where(
            SupplierOffer.id == offer_id,
            SupplierOffer.organization_id == user.organization_id,
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="报价不存在")
    offer, product, brand, supplier_sku, commercial_mode = row

    before_stock = offer.stock_qty
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        if field == "currency" and value:
            value = value.upper()
        setattr(offer, field, value)

    if "stock_qty" in changes and offer.stock_qty != before_stock:
        db.add(
            InventorySnapshot(
                offer_id=offer.id,
                quantity=offer.stock_qty,
                source="MANUAL",
            )
        )

    record_event(
        db,
        event_type="OFFER_UPDATED",
        entity_type="SupplierOffer",
        entity_id=offer.id,
        organization_id=user.organization_id,
        actor_type="USER",
        actor_id=user.id,
        payload={"changes": {key: str(value) for key, value in changes.items()}},
    )
    db.commit()
    db.refresh(offer)
    return offer_view(offer, product, brand, supplier_sku, commercial_mode)
