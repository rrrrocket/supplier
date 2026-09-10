from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.deps import DbSession, SupplierUser
from app.models.entities import Brand, CatalogStatus, SupplierBrandCooperation
from app.schemas.catalog import CooperationUpdate, SupplierBrandCooperationView
from app.services.catalog import replace_active_cooperation


router = APIRouter(prefix="/supplier-catalog", tags=["供应商品牌目录"])


@router.get(
    "/brand-cooperations",
    response_model=list[SupplierBrandCooperationView],
)
def list_brand_cooperations(
    db: DbSession,
    user: SupplierUser,
) -> list[SupplierBrandCooperationView]:
    rows = db.execute(
        select(SupplierBrandCooperation, Brand)
        .join(Brand, Brand.id == SupplierBrandCooperation.brand_id)
        .where(
            SupplierBrandCooperation.supplier_id == user.organization_id,
            SupplierBrandCooperation.status == CatalogStatus.ACTIVE.value,
        )
        .order_by(Brand.name)
    ).all()
    return [
        SupplierBrandCooperationView(
            brand_id=brand.id,
            brand_code=brand.code,
            brand_name=brand.name,
            commercial_mode=cooperation.commercial_mode,
            status=cooperation.status,
        )
        for cooperation, brand in rows
    ]


@router.put(
    "/brand-cooperations/{brand_id}",
    response_model=SupplierBrandCooperationView,
)
def update_brand_commercial_mode(
    brand_id: str,
    payload: CooperationUpdate,
    db: DbSession,
    user: SupplierUser,
) -> SupplierBrandCooperationView:
    brand = db.get(Brand, brand_id)
    cooperation = db.scalar(
        select(SupplierBrandCooperation).where(
            SupplierBrandCooperation.supplier_id == user.organization_id,
            SupplierBrandCooperation.brand_id == brand_id,
            SupplierBrandCooperation.status == CatalogStatus.ACTIVE.value,
        )
    )
    if brand is None or cooperation is None:
        raise HTTPException(status_code=404, detail="当前供应商未关联该品牌")
    updated = replace_active_cooperation(
        db,
        supplier_id=user.organization_id,
        brand_id=brand_id,
        commercial_mode=payload.commercial_mode,
        actor_id=user.id,
    )
    db.commit()
    db.refresh(updated)
    return SupplierBrandCooperationView(
        brand_id=brand.id,
        brand_code=brand.code,
        brand_name=brand.name,
        commercial_mode=updated.commercial_mode,
        status=updated.status,
    )
