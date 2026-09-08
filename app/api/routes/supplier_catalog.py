from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import DbSession, SupplierUser
from app.models.entities import Brand, CatalogStatus, SupplierBrandCooperation
from app.schemas.catalog import SupplierBrandCooperationView


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
