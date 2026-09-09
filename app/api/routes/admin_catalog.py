from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import DbSession
from app.api.routes.admin import PlatformAdmin
from app.models.entities import (
    Brand,
    CatalogStatus,
    IntegrationClient,
    IntegrationClientType,
    Organization,
    OrganizationType,
    SupplierBrandCooperation,
)
from app.schemas.catalog import BrandCreate, BrandView, CooperationUpdate, CooperationView
from app.schemas.integration import (
    IntegrationClientCreate,
    IntegrationClientCredential,
    IntegrationClientView,
)
from app.services.catalog import normalize_brand_name, replace_active_cooperation, resolve_brand
from app.services.events import record_event
from app.services.integration_clients import (
    create_client_with_unique_token,
    integration_client_credential,
    integration_client_view,
    rotate_client_with_unique_token,
)


router = APIRouter(prefix="/admin", tags=["平台品牌管理"])

def require_integration_client(db: DbSession, client_id: str) -> IntegrationClient:
    client = db.get(IntegrationClient, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="集成调用方不存在")
    return client


@router.get(
    "/integration-clients",
    response_model=list[IntegrationClientView],
)
def list_integration_clients(
    db: DbSession,
    _: PlatformAdmin,
) -> list[IntegrationClientView]:
    clients = db.scalars(
        select(IntegrationClient).order_by(IntegrationClient.name, IntegrationClient.id)
    ).all()
    return [integration_client_view(client) for client in clients]


@router.post(
    "/integration-clients",
    response_model=IntegrationClientCredential,
    status_code=status.HTTP_201_CREATED,
)
def create_integration_client(
    payload: IntegrationClientCreate,
    response: Response,
    db: DbSession,
    admin: PlatformAdmin,
) -> IntegrationClientCredential:
    name = " ".join(payload.name.strip().split())
    if not name:
        raise HTTPException(status_code=422, detail="调用方名称不能为空")

    expires_at = (
        payload.expires_at.astimezone(timezone.utc)
        if payload.expires_at is not None
        else None
    )
    client, plaintext = create_client_with_unique_token(
        db,
        name=name,
        scopes=[scope.value for scope in dict.fromkeys(payload.scopes)],
        expires_at=expires_at,
        client_type=IntegrationClientType.SYSTEM.value,
        owner_organization_id=None,
    )
    record_event(
        db,
        event_type="INTEGRATION_CLIENT_CREATED",
        entity_type="IntegrationClient",
        entity_id=client.id,
        organization_id=admin.organization_id,
        actor_type="USER",
        actor_id=admin.id,
        payload={"client_name": client.name, "scopes": client.scopes},
    )
    db.commit()
    db.refresh(client)
    response.headers["Cache-Control"] = "no-store"
    return integration_client_credential(client, plaintext)


@router.post(
    "/integration-clients/{client_id}/rotate",
    response_model=IntegrationClientCredential,
)
def rotate_integration_client(
    client_id: str,
    response: Response,
    db: DbSession,
    admin: PlatformAdmin,
) -> IntegrationClientCredential:
    client = db.scalar(
        select(IntegrationClient).where(
            IntegrationClient.id == client_id,
            IntegrationClient.client_type == IntegrationClientType.SYSTEM.value,
        )
    )
    if client is None:
        raise HTTPException(status_code=404, detail="集成调用方不存在")
    now = datetime.now(timezone.utc)
    if not client.is_active or (
        client.expires_at is not None
        and client.expires_at.astimezone(timezone.utc) <= now
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="已撤销或已过期的凭证不能轮换，请新建调用方",
        )
    plaintext = rotate_client_with_unique_token(db, client)
    record_event(
        db,
        event_type="INTEGRATION_CLIENT_ROTATED",
        entity_type="IntegrationClient",
        entity_id=client.id,
        organization_id=admin.organization_id,
        actor_type="USER",
        actor_id=admin.id,
        payload={"client_name": client.name},
    )
    db.commit()
    db.refresh(client)
    response.headers["Cache-Control"] = "no-store"
    return integration_client_credential(client, plaintext)


@router.post(
    "/integration-clients/{client_id}/revoke",
    response_model=IntegrationClientView,
)
def revoke_integration_client(
    client_id: str,
    db: DbSession,
    admin: PlatformAdmin,
) -> IntegrationClientView:
    client = require_integration_client(db, client_id)
    client.is_active = False
    record_event(
        db,
        event_type="INTEGRATION_CLIENT_REVOKED",
        entity_type="IntegrationClient",
        entity_id=client.id,
        organization_id=admin.organization_id,
        actor_type="USER",
        actor_id=admin.id,
        payload={"client_name": client.name},
    )
    db.commit()
    db.refresh(client)
    return integration_client_view(client)


def brand_view(brand: Brand) -> BrandView:
    return BrandView.model_validate(brand)


def cooperation_view(
    cooperation: SupplierBrandCooperation,
    brand: Brand,
) -> CooperationView:
    return CooperationView(
        id=cooperation.id,
        supplier_id=cooperation.supplier_id,
        brand_id=brand.id,
        brand_name=brand.name,
        commercial_mode=cooperation.commercial_mode,
        status=cooperation.status,
        valid_from=cooperation.valid_from,
        valid_to=cooperation.valid_to,
        updated_at=cooperation.updated_at,
    )


def require_supplier(db: DbSession, supplier_id: str) -> Organization:
    supplier = db.get(Organization, supplier_id)
    if supplier is None or supplier.organization_type != OrganizationType.SUPPLIER.value:
        raise HTTPException(status_code=404, detail="供应商不存在")
    return supplier


def clean_aliases(name: str, aliases: list[str]) -> list[str]:
    normalized_name = normalize_brand_name(name)
    result: list[str] = []
    seen = {normalized_name}
    for alias in aliases:
        display_alias = " ".join(alias.strip().split())
        normalized_alias = normalize_brand_name(display_alias)
        if normalized_alias and normalized_alias not in seen:
            seen.add(normalized_alias)
            result.append(display_alias)
    return result


@router.get("/brands", response_model=list[BrandView])
def list_brands(
    db: DbSession,
    _: PlatformAdmin,
    q: str | None = Query(default=None, max_length=160),
) -> list[BrandView]:
    brands = db.scalars(select(Brand).order_by(Brand.name, Brand.id)).all()
    normalized_query = normalize_brand_name(q or "")
    if normalized_query:
        brands = [
            brand
            for brand in brands
            if any(
                normalized_query in normalize_brand_name(value)
                for value in (brand.code, brand.name, *brand.aliases)
            )
        ]
    return [brand_view(brand) for brand in brands]


@router.post("/brands", response_model=BrandView, status_code=status.HTTP_201_CREATED)
def create_brand(
    payload: BrandCreate,
    response: Response,
    db: DbSession,
    admin: PlatformAdmin,
) -> BrandView:
    name = " ".join(payload.name.strip().split())
    normalized_name = normalize_brand_name(name)
    if not normalized_name:
        raise HTTPException(status_code=422, detail="品牌名称不能为空")

    code = payload.code.strip() if payload.code is not None else None
    if payload.code is not None and not code:
        raise HTTPException(status_code=422, detail="品牌编码不能为空")

    existing_name = db.scalar(
        select(Brand).where(Brand.normalized_name == normalized_name)
    )
    if existing_name is not None:
        if code is not None and existing_name.code.lower() != code.lower():
            raise HTTPException(status_code=409, detail="品牌名称已关联其他品牌编码")
        response.status_code = status.HTTP_200_OK
        return brand_view(existing_name)

    try:
        if code is not None:
            existing_code = db.scalar(
                select(Brand).where(func.lower(Brand.code) == code.lower())
            )
            if existing_code is not None:
                raise HTTPException(status_code=409, detail="品牌编码已存在")
            brand = Brand(
                code=code,
                name=name,
                normalized_name=normalized_name,
                aliases=clean_aliases(name, payload.aliases),
                status=CatalogStatus.ACTIVE.value,
            )
            db.add(brand)
            db.flush()
        else:
            brand = resolve_brand(db, name)
            brand.aliases = clean_aliases(name, payload.aliases)
    except IntegrityError as exc:
        db.rollback()
        canonical = db.scalar(
            select(Brand).where(Brand.normalized_name == normalized_name)
        )
        if canonical is not None:
            if code is not None and canonical.code.lower() != code.lower():
                raise HTTPException(
                    status_code=409,
                    detail="品牌名称已关联其他品牌编码",
                ) from exc
            response.status_code = status.HTTP_200_OK
            return brand_view(canonical)
        if code is not None and db.scalar(
            select(Brand).where(func.lower(Brand.code) == code.lower())
        ) is not None:
            raise HTTPException(status_code=409, detail="品牌编码已存在") from exc
        raise HTTPException(status_code=409, detail="品牌名称或编码已存在") from exc

    record_event(
        db,
        event_type="BRAND_CREATED",
        entity_type="Brand",
        entity_id=brand.id,
        organization_id=admin.organization_id,
        actor_type="USER",
        actor_id=admin.id,
        payload={"brand_code": brand.code, "brand_name": brand.name},
    )
    db.commit()
    db.refresh(brand)
    return brand_view(brand)


@router.get(
    "/suppliers/{supplier_id}/brand-cooperations",
    response_model=list[CooperationView],
)
def list_supplier_brand_cooperations(
    supplier_id: str,
    db: DbSession,
    _: PlatformAdmin,
) -> list[CooperationView]:
    require_supplier(db, supplier_id)
    rows = db.execute(
        select(SupplierBrandCooperation, Brand)
        .join(Brand, Brand.id == SupplierBrandCooperation.brand_id)
        .where(
            SupplierBrandCooperation.supplier_id == supplier_id,
            SupplierBrandCooperation.status == CatalogStatus.ACTIVE.value,
        )
        .order_by(Brand.name, Brand.id)
    ).all()
    return [cooperation_view(cooperation, brand) for cooperation, brand in rows]


@router.put(
    "/suppliers/{supplier_id}/brands/{brand_id}/cooperation",
    response_model=CooperationView,
)
def update_supplier_brand_cooperation(
    supplier_id: str,
    brand_id: str,
    payload: CooperationUpdate,
    db: DbSession,
    admin: PlatformAdmin,
) -> CooperationView:
    require_supplier(db, supplier_id)
    brand = db.get(Brand, brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="品牌不存在")

    cooperation = replace_active_cooperation(
        db,
        supplier_id=supplier_id,
        brand_id=brand_id,
        commercial_mode=payload.commercial_mode,
        actor_id=admin.id,
    )
    db.commit()
    db.refresh(cooperation)
    return cooperation_view(cooperation, brand)
