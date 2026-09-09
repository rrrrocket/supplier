from __future__ import annotations

from datetime import timezone

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import DbSession, OperatorUser
from app.models.entities import (
    BindingStatus,
    CooperationStatus,
    ErpBinding,
    OperatorProfile,
    OperatorSupplierCooperation,
    Organization,
    OrganizationType,
    SupplierProfile,
    SupplierStatus,
    IntegrationClient,
    IntegrationClientType,
)
from app.api.routes.admin_catalog import (
    create_client_with_unique_token,
    integration_client_credential,
    integration_client_view,
    rotate_client_with_unique_token,
)
from app.schemas.integration import IntegrationClientCreate, IntegrationClientCredential, IntegrationClientPage, IntegrationClientView
from app.schemas.operator import OperatorDashboardView, OperatorProfileUpdate, OperatorProfileView
from app.services.events import record_event


router = APIRouter(prefix="/operator", tags=["运营商工作台"])


def owned_client(db: DbSession, client_id: str, organization_id: str) -> IntegrationClient:
    client = db.scalar(select(IntegrationClient).where(
        IntegrationClient.id == client_id,
        IntegrationClient.client_type == IntegrationClientType.OPERATOR.value,
        IntegrationClient.owner_organization_id == organization_id,
    ))
    if client is None:
        raise HTTPException(status_code=404, detail="集成调用方不存在")
    return client


@router.get("/integration-clients", response_model=IntegrationClientPage)
def list_operator_clients(
    db: DbSession, user: OperatorUser, page: int = Query(1, ge=1),
    page_size: int = Query(50),
) -> IntegrationClientPage:
    if page_size not in {20, 50, 100, 200}:
        raise HTTPException(status_code=422, detail="页面行数仅支持 20、50、100 或 200")
    condition = (
        IntegrationClient.owner_organization_id == user.organization_id,
        IntegrationClient.client_type == IntegrationClientType.OPERATOR.value,
    )
    total = db.scalar(select(func.count(IntegrationClient.id)).where(*condition)) or 0
    clients = db.scalars(select(IntegrationClient).where(
        *condition
    ).order_by(IntegrationClient.name, IntegrationClient.id)
        .offset((page-1)*page_size).limit(page_size)).all()
    return IntegrationClientPage(
        items=[integration_client_view(item) for item in clients], total=total,
        page=page, page_size=page_size,
    )


@router.post("/integration-clients", response_model=IntegrationClientCredential, status_code=status.HTTP_201_CREATED)
def create_operator_client(
    payload: IntegrationClientCreate, response: Response, db: DbSession, user: OperatorUser
) -> IntegrationClientCredential:
    expires_at = payload.expires_at.astimezone(timezone.utc) if payload.expires_at else None
    client, plaintext = create_client_with_unique_token(
        db, name=" ".join(payload.name.strip().split()),
        scopes=[scope.value for scope in dict.fromkeys(payload.scopes)], expires_at=expires_at,
        client_type=IntegrationClientType.OPERATOR.value,
        owner_organization_id=user.organization_id,
    )
    record_event(db, event_type="OPERATOR_INTEGRATION_CLIENT_CREATED", entity_type="IntegrationClient", entity_id=client.id, organization_id=user.organization_id, actor_type="USER", actor_id=user.id, payload={"client_name": client.name, "scopes": client.scopes})
    db.commit(); db.refresh(client)
    response.headers["Cache-Control"] = "no-store"
    return integration_client_credential(client, plaintext)


@router.post("/integration-clients/{client_id}/rotate", response_model=IntegrationClientCredential)
def rotate_operator_client(client_id: str, response: Response, db: DbSession, user: OperatorUser) -> IntegrationClientCredential:
    client = owned_client(db, client_id, user.organization_id)
    if not client.is_active: raise HTTPException(status_code=409, detail="已停用凭证不能轮换")
    plaintext = rotate_client_with_unique_token(db, client)
    record_event(
        db, event_type="OPERATOR_INTEGRATION_CLIENT_ROTATED", entity_type="IntegrationClient",
        entity_id=client.id, organization_id=user.organization_id,
        actor_type="USER", actor_id=user.id,
    )
    db.commit(); db.refresh(client); response.headers["Cache-Control"] = "no-store"
    return integration_client_credential(client, plaintext)


@router.post("/integration-clients/{client_id}/revoke", response_model=IntegrationClientView)
def revoke_operator_client(client_id: str, db: DbSession, user: OperatorUser) -> IntegrationClientView:
    client = owned_client(db, client_id, user.organization_id); client.is_active = False
    record_event(
        db, event_type="OPERATOR_INTEGRATION_CLIENT_REVOKED", entity_type="IntegrationClient",
        entity_id=client.id, organization_id=user.organization_id,
        actor_type="USER", actor_id=user.id,
    )
    db.commit(); db.refresh(client)
    return integration_client_view(client)


def profile_view(profile: OperatorProfile) -> OperatorProfileView:
    return OperatorProfileView(
        id=profile.id, organization_id=profile.organization_id,
        company_name=profile.company_name,
        unified_social_credit_code=profile.unified_social_credit_code,
        operator_type=profile.operator_type, province=profile.province, city=profile.city,
        contact_name=profile.contact_name, contact_phone=profile.contact_phone,
        contact_email=profile.contact_email, website=profile.website, erp_name=profile.erp_name,
        sales_channels=profile.sales_channels, categories=profile.categories,
        target_markets=profile.target_markets,
        qualification_files=profile.qualification_files,
    )


def get_profile(db: DbSession, organization_id: str) -> OperatorProfile:
    profile = db.scalar(
        select(OperatorProfile).where(OperatorProfile.organization_id == organization_id)
    )
    if profile is None:
        raise HTTPException(status_code=404, detail="运营商资料不存在")
    return profile


@router.get("/profile", response_model=OperatorProfileView)
def read_profile(db: DbSession, user: OperatorUser) -> OperatorProfileView:
    return profile_view(get_profile(db, user.organization_id))


@router.patch("/profile", response_model=OperatorProfileView)
def update_profile(
    payload: OperatorProfileUpdate, db: DbSession, user: OperatorUser
) -> OperatorProfileView:
    profile = get_profile(db, user.organization_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(profile, field, str(value).lower() if field == "contact_email" else value)
    record_event(
        db, event_type="OPERATOR_PROFILE_UPDATED", entity_type="OperatorProfile",
        entity_id=profile.id, organization_id=user.organization_id,
        actor_type="USER", actor_id=user.id,
    )
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="该统一社会信用代码已关联运营商组织") from error
    db.refresh(profile)
    return profile_view(profile)


@router.get("/dashboard", response_model=OperatorDashboardView)
def dashboard(db: DbSession, user: OperatorUser) -> OperatorDashboardView:
    available = db.scalar(
        select(func.count(Organization.id)).join(
            SupplierProfile, SupplierProfile.organization_id == Organization.id
        ).where(
            Organization.organization_type == OrganizationType.SUPPLIER.value,
            Organization.is_active.is_(True),
            SupplierProfile.status == SupplierStatus.APPROVED.value,
        )
    ) or 0
    pending = db.scalar(select(func.count(OperatorSupplierCooperation.id)).where(
        OperatorSupplierCooperation.operator_id == user.organization_id,
        OperatorSupplierCooperation.status == CooperationStatus.PENDING.value,
    )) or 0
    active = db.scalar(select(func.count(OperatorSupplierCooperation.id)).where(
        OperatorSupplierCooperation.operator_id == user.organization_id,
        OperatorSupplierCooperation.status == CooperationStatus.ACTIVE.value,
    )) or 0
    bindings = db.scalar(select(func.count(ErpBinding.id)).where(
        ErpBinding.operator_id == user.organization_id,
        ErpBinding.status == BindingStatus.ACTIVE.value,
    )) or 0
    return OperatorDashboardView(
        available_suppliers=available, pending_cooperations=pending,
        active_cooperations=active, active_bindings=bindings,
    )
