from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import DbSession, SupplierUser
from app.models.entities import Product, SupplierOffer
from app.schemas.product import ProductCreate, ProductView
from app.services.events import record_event


router = APIRouter(prefix="/products", tags=["商品主数据"])


def product_view(product: Product, offer_count: int = 0) -> ProductView:
    return ProductView(
        id=product.id,
        name=product.name,
        brand=product.brand,
        model=product.model,
        category=product.category,
        description=product.description,
        attributes=product.attributes,
        status=product.status,
        created_at=product.created_at,
        updated_at=product.updated_at,
        offer_count=offer_count,
    )


@router.get("", response_model=list[ProductView])
def list_products(
    db: DbSession,
    user: SupplierUser,
    q: str | None = Query(default=None, max_length=120),
    product_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[ProductView]:
    offer_count = (
        select(SupplierOffer.product_id, func.count(SupplierOffer.id).label("offer_count"))
        .where(SupplierOffer.organization_id == user.organization_id)
        .group_by(SupplierOffer.product_id)
        .subquery()
    )
    stmt = (
        select(Product, func.coalesce(offer_count.c.offer_count, 0))
        .outerjoin(offer_count, offer_count.c.product_id == Product.id)
        .where(Product.created_by_organization_id == user.organization_id)
        .order_by(Product.updated_at.desc())
        .limit(limit)
    )
    if q:
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Product.name.ilike(pattern),
                Product.brand.ilike(pattern),
                Product.model.ilike(pattern),
                Product.category.ilike(pattern),
            )
        )
    if product_status:
        stmt = stmt.where(Product.status == product_status)

    rows = db.execute(stmt).all()
    return [product_view(product, int(count)) for product, count in rows]


@router.post("", response_model=ProductView, status_code=status.HTTP_201_CREATED)
def create_product(
    payload: ProductCreate,
    db: DbSession,
    user: SupplierUser,
) -> ProductView:
    product = Product(
        created_by_organization_id=user.organization_id,
        name=payload.name.strip(),
        brand=(payload.brand or "").strip() or None,
        model=(payload.model or "").strip() or None,
        category=payload.category.strip(),
        description=(payload.description or "").strip() or None,
        attributes=payload.attributes,
        status=payload.status,
    )
    db.add(product)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="相同品牌、型号和名称的商品已经存在",
        ) from exc

    record_event(
        db,
        event_type="PRODUCT_CREATED",
        entity_type="Product",
        entity_id=product.id,
        organization_id=user.organization_id,
        actor_type="USER",
        actor_id=user.id,
        payload={"name": product.name, "category": product.category},
    )
    db.commit()
    db.refresh(product)
    return product_view(product)


@router.get("/{product_id}", response_model=ProductView)
def get_product(product_id: str, db: DbSession, user: SupplierUser) -> ProductView:
    product = db.scalar(
        select(Product).where(
            Product.id == product_id,
            Product.created_by_organization_id == user.organization_id,
        )
    )
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="商品不存在")
    count = db.scalar(
        select(func.count(SupplierOffer.id)).where(
            SupplierOffer.organization_id == user.organization_id,
            SupplierOffer.product_id == product.id,
        )
    ) or 0
    return product_view(product, int(count))
