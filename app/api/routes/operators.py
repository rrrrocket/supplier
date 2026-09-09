from __future__ import annotations

from fastapi import APIRouter, HTTPException
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
)
from app.schemas.operator import OperatorDashboardView, OperatorProfileUpdate, OperatorProfileView
from app.services.events import record_event


router = APIRouter(prefix="/operator", tags=["运营商工作台"])


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
