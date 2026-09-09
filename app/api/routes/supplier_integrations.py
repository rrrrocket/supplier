from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import func, select

from app.api.deps import DbSession, SupplierUser
from app.models.entities import IntegrationClient, IntegrationClientType
from app.schemas.integration import (
    IntegrationClientCreate,
    IntegrationClientCredential,
    IntegrationClientPage,
    IntegrationClientView,
)
from app.services.events import record_event
from app.services.integration_clients import (
    create_client_with_unique_token,
    integration_client_credential,
    integration_client_view,
    rotate_client_with_unique_token,
)


router = APIRouter(
    prefix="/supplier/integration-clients",
    tags=["供应商 ERP 接入"],
)

PAGE_SIZES = {20, 50, 100, 200}


def owned_supplier_client(
    db: DbSession,
    client_id: str,
    organization_id: str,
) -> IntegrationClient:
    client = db.scalar(
        select(IntegrationClient).where(
            IntegrationClient.id == client_id,
            IntegrationClient.client_type == IntegrationClientType.SUPPLIER.value,
            IntegrationClient.owner_organization_id == organization_id,
        )
    )
    if client is None:
        raise HTTPException(status_code=404, detail="凭证不存在或不可访问")
    return client


@router.get("", response_model=IntegrationClientPage)
def list_supplier_integration_clients(
    db: DbSession,
    user: SupplierUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(50),
) -> IntegrationClientPage:
    if page_size not in PAGE_SIZES:
        raise HTTPException(
            status_code=422,
            detail="页面行数仅支持 20、50、100 或 200",
        )
    condition = (
        IntegrationClient.client_type == IntegrationClientType.SUPPLIER.value,
        IntegrationClient.owner_organization_id == user.organization_id,
    )
    total = db.scalar(select(func.count(IntegrationClient.id)).where(*condition)) or 0
    clients = db.scalars(
        select(IntegrationClient)
        .where(*condition)
        .order_by(IntegrationClient.name, IntegrationClient.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return IntegrationClientPage(
        items=[integration_client_view(client) for client in clients],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "",
    response_model=IntegrationClientCredential,
    status_code=status.HTTP_201_CREATED,
)
def create_supplier_integration_client(
    payload: IntegrationClientCreate,
    response: Response,
    db: DbSession,
    user: SupplierUser,
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
        client_type=IntegrationClientType.SUPPLIER.value,
        owner_organization_id=user.organization_id,
        issuer_user_id=user.id,
    )
    record_event(
        db,
        event_type="SUPPLIER_INTEGRATION_CLIENT_CREATED",
        entity_type="IntegrationClient",
        entity_id=client.id,
        organization_id=user.organization_id,
        actor_type="USER",
        actor_id=user.id,
        payload={"client_name": client.name, "scopes": client.scopes},
    )
    db.commit()
    db.refresh(client)
    response.headers["Cache-Control"] = "no-store"
    return integration_client_credential(client, plaintext)


@router.post(
    "/{client_id}/rotate",
    response_model=IntegrationClientCredential,
)
def rotate_supplier_integration_client(
    client_id: str,
    response: Response,
    db: DbSession,
    user: SupplierUser,
) -> IntegrationClientCredential:
    client = owned_supplier_client(db, client_id, user.organization_id)
    now = datetime.now(timezone.utc)
    if not client.is_active or (
        client.expires_at is not None
        and client.expires_at.astimezone(timezone.utc) <= now
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="已撤销或已过期的凭证不能轮换，请新建调用方",
        )
    plaintext = rotate_client_with_unique_token(
        db,
        client,
        issuer_user_id=user.id,
    )
    record_event(
        db,
        event_type="SUPPLIER_INTEGRATION_CLIENT_ROTATED",
        entity_type="IntegrationClient",
        entity_id=client.id,
        organization_id=user.organization_id,
        actor_type="USER",
        actor_id=user.id,
        payload={"client_name": client.name},
    )
    db.commit()
    db.refresh(client)
    response.headers["Cache-Control"] = "no-store"
    return integration_client_credential(client, plaintext)


@router.post(
    "/{client_id}/revoke",
    response_model=IntegrationClientView,
)
def revoke_supplier_integration_client(
    client_id: str,
    db: DbSession,
    user: SupplierUser,
) -> IntegrationClientView:
    client = owned_supplier_client(db, client_id, user.organization_id)
    client.is_active = False
    record_event(
        db,
        event_type="SUPPLIER_INTEGRATION_CLIENT_REVOKED",
        entity_type="IntegrationClient",
        entity_id=client.id,
        organization_id=user.organization_id,
        actor_type="USER",
        actor_id=user.id,
        payload={"client_name": client.name},
    )
    db.commit()
    db.refresh(client)
    return integration_client_view(client)
