from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import DbSession, SupplierUser
from app.models.entities import Brand, InventorySnapshot, Product, SupplierOffer, SupplierSku
from app.schemas.product import OfferCreate, OfferUpdate, OfferView
from app.services.catalog import ensure_supplier_sku
from app.services.events import record_event


router = APIRouter(prefix="/offers", tags=["供应报价"])


def offer_view(
    offer: SupplierOffer,
    product: Product,
    brand: Brand,
    supplier_sku: SupplierSku,
) -> OfferView:
    return OfferView(
        id=offer.id,
        supplier_sku_id=supplier_sku.id,
        supplier_sku_code=supplier_sku.supplier_sku_code,
        supplier_sku=supplier_sku.supplier_sku_code,
        product_id=offer.product_id,
        product_name=product.name,
        brand_id=brand.id,
        brand=brand.name,
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
    q: str | None = Query(default=None, max_length=120),
    brand: str | None = Query(default=None, max_length=120),
    offer_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> list[OfferView]:
    stmt = (
        select(SupplierOffer, Product, Brand, SupplierSku)
        .join(Product, Product.id == SupplierOffer.product_id)
        .join(Brand, Brand.id == Product.brand_id)
        .join(SupplierSku, SupplierSku.id == SupplierOffer.supplier_sku_id)
        .where(SupplierOffer.organization_id == user.organization_id)
    )
    if q:
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                SupplierOffer.supplier_sku.ilike(pattern),
                Product.name.ilike(pattern),
                Product.brand.ilike(pattern),
                Product.model.ilike(pattern),
            )
        )
    if offer_status:
        stmt = stmt.where(SupplierOffer.status == offer_status)
    if brand:
        stmt = stmt.where(Product.brand == brand.strip())
    stmt = (
        stmt.order_by(SupplierOffer.updated_at.desc(), SupplierOffer.id.desc())
        .offset(offset)
        .limit(limit)
    )

    return [
        offer_view(offer, product, brand, supplier_sku)
        for offer, product, brand, supplier_sku in db.execute(stmt).all()
    ]


@router.get("/brands", response_model=list[str])
def list_offer_brands(db: DbSession, user: SupplierUser) -> list[str]:
    return list(
        db.scalars(
            select(Product.brand)
            .join(SupplierOffer, SupplierOffer.product_id == Product.id)
            .where(
                SupplierOffer.organization_id == user.organization_id,
                Product.brand.is_not(None),
                Product.brand != "",
            )
            .distinct()
            .order_by(Product.brand)
        ).all()
    )


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
    if product.brand_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="product does not belong to brand",
        )

    supplier_sku_code = payload.supplier_sku_code
    if supplier_sku_code is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="supplier_sku_code or supplier_sku is required",
        )

    try:
        supplier_sku = ensure_supplier_sku(
            db,
            supplier_id=user.organization_id,
            brand_id=product.brand_id,
            product_id=product.id,
            variant_id=None,
            supplier_sku_code=supplier_sku_code,
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

    offer = SupplierOffer(
        organization_id=user.organization_id,
        product_id=product.id,
        supplier_sku_id=supplier_sku.id,
        supplier_sku=supplier_sku.supplier_sku_code,
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
        payload={"supplier_sku": offer.supplier_sku, "product_name": product.name},
    )
    db.commit()
    db.refresh(offer)
    return offer_view(offer, product, brand, supplier_sku)


@router.patch("/{offer_id}", response_model=OfferView)
def update_offer(
    offer_id: str,
    payload: OfferUpdate,
    db: DbSession,
    user: SupplierUser,
) -> OfferView:
    row = db.execute(
        select(SupplierOffer, Product, Brand, SupplierSku)
        .join(Product, Product.id == SupplierOffer.product_id)
        .join(Brand, Brand.id == Product.brand_id)
        .join(SupplierSku, SupplierSku.id == SupplierOffer.supplier_sku_id)
        .where(
            SupplierOffer.id == offer_id,
            SupplierOffer.organization_id == user.organization_id,
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="报价不存在")
    offer, product, brand, supplier_sku = row

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
    return offer_view(offer, product, brand, supplier_sku)
