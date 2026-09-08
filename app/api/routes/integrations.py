from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import AwareDatetime
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.api.deps import DbSession
from app.api.integration_deps import BrandReader, SkuReader, SupplierReader
from app.models.entities import (
    Brand,
    CatalogStatus,
    Organization,
    OrganizationType,
    Product,
    SupplierBrandCooperation,
    SupplierProfile,
    SupplierSku,
    SupplierStatus,
)
from app.schemas.integration import (
    SupplierBrandIntegrationPage,
    SupplierBrandIntegrationView,
    SupplierIntegrationPage,
    SupplierIntegrationView,
    SupplierSkuIntegrationPage,
    SupplierSkuIntegrationView,
)
from app.services.integration_pagination import decode_cursor, encode_cursor


router = APIRouter(prefix="/integrations/v1", tags=["通用系统集成"])

ACTIVE = CatalogStatus.ACTIVE.value
INACTIVE = CatalogStatus.INACTIVE.value


def utc_value(value: datetime) -> datetime:
    return value.astimezone(timezone.utc)


def after_cursor(
    updated_at: ColumnElement[datetime],
    entity_id: ColumnElement[str],
    cursor: str,
) -> ColumnElement[bool]:
    cursor_updated_at, cursor_id = decode_cursor(cursor)
    return or_(
        updated_at > cursor_updated_at,
        and_(updated_at == cursor_updated_at, entity_id > cursor_id),
    )


def page_cursor(
    rows: list[Any],
    *,
    limit: int,
    updated_at_index: int,
    id_index: int,
) -> tuple[list[Any], str | None]:
    page = rows[:limit]
    if len(rows) <= limit:
        return page, None
    last = page[-1]
    return page, encode_cursor(last[updated_at_index], last[id_index])


def supplier_active_condition() -> ColumnElement[bool]:
    return and_(
        Organization.is_active.is_(True),
        SupplierProfile.status == SupplierStatus.APPROVED.value,
    )


def supplier_updated_at() -> ColumnElement[datetime]:
    return func.greatest(
        Organization.updated_at,
        func.coalesce(SupplierProfile.updated_at, Organization.updated_at),
    )


def supplier_view(
    supplier: Organization,
    effective_updated_at: datetime,
    resource_status: str,
) -> SupplierIntegrationView:
    return SupplierIntegrationView(
        supplier_id=supplier.id,
        supplier_code=supplier.code,
        supplier_name=supplier.name,
        status=resource_status,
        updated_at=effective_updated_at,
    )


def supplier_context(
    db: Session,
    supplier_id: str,
) -> tuple[Organization, SupplierProfile | None]:
    row = db.execute(
        select(Organization, SupplierProfile)
        .outerjoin(
            SupplierProfile,
            SupplierProfile.organization_id == Organization.id,
        )
        .where(
            Organization.id == supplier_id,
            Organization.organization_type == OrganizationType.SUPPLIER.value,
        )
    ).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "SUPPLIER_NOT_FOUND", "message": "供应商不存在"},
        )
    return row[0], row[1]


def is_supplier_active(
    supplier: Organization,
    profile: SupplierProfile | None,
) -> bool:
    return bool(
        supplier.is_active
        and profile is not None
        and profile.status == SupplierStatus.APPROVED.value
    )


def ranked_cooperations(supplier_id: str):
    active_first = case(
        (SupplierBrandCooperation.status == ACTIVE, 0),
        else_=1,
    )
    return (
        select(
            SupplierBrandCooperation.id.label("cooperation_id"),
            SupplierBrandCooperation.brand_id.label("brand_id"),
            SupplierBrandCooperation.commercial_mode.label("commercial_mode"),
            SupplierBrandCooperation.status.label("cooperation_status"),
            SupplierBrandCooperation.updated_at.label("cooperation_updated_at"),
            func.row_number()
            .over(
                partition_by=SupplierBrandCooperation.brand_id,
                order_by=(
                    active_first,
                    SupplierBrandCooperation.updated_at.desc(),
                    SupplierBrandCooperation.id.desc(),
                ),
            )
            .label("cooperation_rank"),
        )
        .where(SupplierBrandCooperation.supplier_id == supplier_id)
        .subquery()
    )


@router.get("/suppliers", response_model=SupplierIntegrationPage)
def list_suppliers(
    db: DbSession,
    _: SupplierReader,
    updated_since: AwareDatetime | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    include_inactive: bool = Query(default=False),
) -> SupplierIntegrationPage:
    effective_updated_at = supplier_updated_at().label("effective_updated_at")
    resource_status = case(
        (supplier_active_condition(), ACTIVE),
        else_=INACTIVE,
    ).label("resource_status")
    statement = (
        select(
            Organization,
            effective_updated_at,
            resource_status,
            Organization.id.label("entity_id"),
        )
        .outerjoin(
            SupplierProfile,
            SupplierProfile.organization_id == Organization.id,
        )
        .where(Organization.organization_type == OrganizationType.SUPPLIER.value)
    )
    if not include_inactive:
        statement = statement.where(supplier_active_condition())
    if updated_since is not None:
        statement = statement.where(effective_updated_at > utc_value(updated_since))
    if cursor is not None:
        statement = statement.where(after_cursor(effective_updated_at, Organization.id, cursor))
    rows = db.execute(
        statement.order_by(effective_updated_at, Organization.id).limit(limit + 1)
    ).all()
    page, next_cursor = page_cursor(
        rows,
        limit=limit,
        updated_at_index=1,
        id_index=3,
    )
    return SupplierIntegrationPage(
        items=[supplier_view(row[0], row[1], row[2]) for row in page],
        next_cursor=next_cursor,
    )


@router.get("/suppliers/{supplier_id}", response_model=SupplierIntegrationView)
def get_supplier(
    supplier_id: str,
    db: DbSession,
    _: SupplierReader,
) -> SupplierIntegrationView:
    effective_updated_at = supplier_updated_at().label("effective_updated_at")
    resource_status = case(
        (supplier_active_condition(), ACTIVE),
        else_=INACTIVE,
    ).label("resource_status")
    row = db.execute(
        select(Organization, effective_updated_at, resource_status)
        .outerjoin(
            SupplierProfile,
            SupplierProfile.organization_id == Organization.id,
        )
        .where(
            Organization.id == supplier_id,
            Organization.organization_type == OrganizationType.SUPPLIER.value,
        )
    ).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "SUPPLIER_NOT_FOUND", "message": "供应商不存在"},
        )
    return supplier_view(row[0], row[1], row[2])


@router.get(
    "/suppliers/{supplier_id}/brands",
    response_model=SupplierBrandIntegrationPage,
)
def list_supplier_brands(
    supplier_id: str,
    db: DbSession,
    _: BrandReader,
    updated_since: AwareDatetime | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    include_inactive: bool = Query(default=False),
) -> SupplierBrandIntegrationPage:
    supplier, profile = supplier_context(db, supplier_id)
    current = ranked_cooperations(supplier_id)
    effective_updated_at = func.greatest(
        Brand.updated_at,
        current.c.cooperation_updated_at,
    ).label("effective_updated_at")
    active_condition = and_(
        is_supplier_active(supplier, profile),
        Brand.status == ACTIVE,
        current.c.cooperation_status == ACTIVE,
    )
    resource_status = case(
        (active_condition, ACTIVE),
        else_=INACTIVE,
    ).label("resource_status")
    statement = (
        select(
            Brand,
            current.c.commercial_mode,
            effective_updated_at,
            resource_status,
            Brand.id.label("entity_id"),
        )
        .join(current, current.c.brand_id == Brand.id)
        .where(current.c.cooperation_rank == 1)
    )
    if not include_inactive:
        statement = statement.where(active_condition)
    if updated_since is not None:
        statement = statement.where(effective_updated_at > utc_value(updated_since))
    if cursor is not None:
        statement = statement.where(after_cursor(effective_updated_at, Brand.id, cursor))
    rows = db.execute(
        statement.order_by(effective_updated_at, Brand.id).limit(limit + 1)
    ).all()
    page, next_cursor = page_cursor(
        rows,
        limit=limit,
        updated_at_index=2,
        id_index=4,
    )
    return SupplierBrandIntegrationPage(
        items=[
            SupplierBrandIntegrationView(
                brand_id=row[0].id,
                brand_code=row[0].code,
                brand_name=row[0].name,
                commercial_mode=row[1],
                status=row[3],
                updated_at=row[2],
            )
            for row in page
        ],
        next_cursor=next_cursor,
    )


@router.get(
    "/suppliers/{supplier_id}/skus",
    response_model=SupplierSkuIntegrationPage,
)
def list_supplier_skus(
    supplier_id: str,
    db: DbSession,
    _: SkuReader,
    updated_since: AwareDatetime | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    include_inactive: bool = Query(default=False),
) -> SupplierSkuIntegrationPage:
    supplier, profile = supplier_context(db, supplier_id)
    current = ranked_cooperations(supplier_id)
    effective_updated_at = func.greatest(
        SupplierSku.updated_at,
        Brand.updated_at,
        Product.updated_at,
        current.c.cooperation_updated_at,
    ).label("effective_updated_at")
    active_condition = and_(
        is_supplier_active(supplier, profile),
        SupplierSku.status == ACTIVE,
        Brand.status == ACTIVE,
        current.c.cooperation_status == ACTIVE,
    )
    resource_status = case(
        (active_condition, ACTIVE),
        else_=INACTIVE,
    ).label("resource_status")
    statement = (
        select(
            SupplierSku,
            Brand,
            Product,
            current.c.commercial_mode,
            effective_updated_at,
            resource_status,
            SupplierSku.id.label("entity_id"),
        )
        .join(Brand, Brand.id == SupplierSku.brand_id)
        .join(
            Product,
            and_(
                Product.id == SupplierSku.product_id,
                Product.created_by_organization_id == supplier_id,
            ),
        )
        .join(current, current.c.brand_id == SupplierSku.brand_id)
        .where(
            SupplierSku.supplier_id == supplier_id,
            current.c.cooperation_rank == 1,
        )
    )
    if not include_inactive:
        statement = statement.where(active_condition)
    if updated_since is not None:
        statement = statement.where(effective_updated_at > utc_value(updated_since))
    if cursor is not None:
        statement = statement.where(
            after_cursor(effective_updated_at, SupplierSku.id, cursor)
        )
    rows = db.execute(
        statement.order_by(effective_updated_at, SupplierSku.id).limit(limit + 1)
    ).all()
    page, next_cursor = page_cursor(
        rows,
        limit=limit,
        updated_at_index=4,
        id_index=6,
    )
    return SupplierSkuIntegrationPage(
        items=[
            SupplierSkuIntegrationView(
                supplier_sku_id=row[0].id,
                supplier_sku_code=row[0].supplier_sku_code,
                brand_id=row[1].id,
                brand_name=row[1].name,
                product_name=row[2].name,
                model=row[2].model,
                manufacturer_part_number=row[0].manufacturer_part_number,
                barcode=row[0].barcode,
                commercial_mode=row[3],
                status=row[5],
                updated_at=row[4],
            )
            for row in page
        ],
        next_cursor=next_cursor,
    )
