from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import DbSession, SupplierUser
from app.models.entities import SupplierProfile
from app.schemas.supplier import SupplierProfileUpdate, SupplierProfileView
from app.services.events import record_event
from app.services.scoring import calculate_profile_completion


router = APIRouter(prefix="/profile", tags=["供应商资料"])


def profile_view(profile: SupplierProfile) -> SupplierProfileView:
    return SupplierProfileView(
        id=profile.id,
        legal_name=profile.legal_name,
        unified_social_credit_code=profile.unified_social_credit_code,
        supplier_type=profile.supplier_type,
        province=profile.province,
        city=profile.city,
        address=profile.address,
        contact_name=profile.contact_name,
        contact_phone=profile.contact_phone,
        contact_email=profile.contact_email,
        website=profile.website,
        categories=profile.categories,
        cooperation_modes=profile.cooperation_modes,
        export_markets=profile.export_markets,
        supports_dropshipping=profile.supports_dropshipping,
        supports_oem=profile.supports_oem,
        has_export_experience=profile.has_export_experience,
        status=profile.status,
        profile_completion=profile.profile_completion,
    )


@router.get("", response_model=SupplierProfileView)
def get_profile(db: DbSession, user: SupplierUser) -> SupplierProfileView:
    profile = db.scalar(
        select(SupplierProfile).where(SupplierProfile.organization_id == user.organization_id)
    )
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="供应商资料不存在")
    return profile_view(profile)


@router.patch("", response_model=SupplierProfileView)
def update_profile(
    payload: SupplierProfileUpdate,
    db: DbSession,
    user: SupplierUser,
) -> SupplierProfileView:
    profile = db.scalar(
        select(SupplierProfile).where(SupplierProfile.organization_id == user.organization_id)
    )
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="供应商资料不存在")

    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        if isinstance(value, str):
            value = value.strip() or None
        if field == "contact_email" and value is not None:
            value = str(value).lower()
        setattr(profile, field, value)

    profile.profile_completion = calculate_profile_completion(profile)
    record_event(
        db,
        event_type="SUPPLIER_PROFILE_UPDATED",
        entity_type="SupplierProfile",
        entity_id=profile.id,
        organization_id=user.organization_id,
        actor_type="USER",
        actor_id=user.id,
        payload={"fields": sorted(changes.keys())},
    )
    db.commit()
    db.refresh(profile)
    return profile_view(profile)
