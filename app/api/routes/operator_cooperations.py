from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import DbSession, OperatorUser
from app.models.entities import (
    BindingStatus, CooperationStatus, ErpBinding, OperatorSupplierCooperation,
    Organization, OrganizationType, SupplierProfile, SupplierStatus,
)
from app.schemas.cooperation import BindingView, CooperationCreate, CooperationView
from app.services.events import record_event


router = APIRouter(prefix="/operator/cooperations", tags=["运营商合作"])


def view(db: DbSession, item: OperatorSupplierCooperation) -> CooperationView:
    binding = db.scalar(select(ErpBinding).where(ErpBinding.cooperation_id == item.id))
    operator = db.get(Organization, item.operator_id)
    supplier = db.get(Organization, item.supplier_id)
    return CooperationView(
        id=item.id, operator_id=item.operator_id, supplier_id=item.supplier_id,
        operator_name=operator.name if operator else None,
        supplier_name=supplier.name if supplier else None,
        status=item.status, categories=item.categories, brands=item.brands,
        sales_channels=item.sales_channels, target_markets=item.target_markets,
        message=item.message, response_notes=item.response_notes, created_at=item.created_at,
        binding=BindingView.model_validate(binding, from_attributes=True) if binding else None,
    )


@router.get("", response_model=list[CooperationView])
def list_cooperations(db: DbSession, user: OperatorUser) -> list[CooperationView]:
    items = db.scalars(select(OperatorSupplierCooperation).where(
        OperatorSupplierCooperation.operator_id == user.organization_id
    ).order_by(OperatorSupplierCooperation.created_at.desc())).all()
    return [view(db, item) for item in items]


@router.post("", response_model=CooperationView, status_code=status.HTTP_201_CREATED)
def create_cooperation(payload: CooperationCreate, db: DbSession, user: OperatorUser) -> CooperationView:
    supplier = db.get(Organization, payload.supplier_id)
    profile = db.scalar(select(SupplierProfile).where(SupplierProfile.organization_id == payload.supplier_id))
    if not supplier or supplier.organization_type != OrganizationType.SUPPLIER.value or not supplier.is_active or not profile or profile.status != SupplierStatus.APPROVED.value:
        raise HTTPException(status_code=404, detail="供应商不存在")
    existing = db.scalar(select(OperatorSupplierCooperation).where(
        OperatorSupplierCooperation.operator_id == user.organization_id,
        OperatorSupplierCooperation.supplier_id == payload.supplier_id,
        OperatorSupplierCooperation.status.in_([CooperationStatus.PENDING.value, CooperationStatus.ACTIVE.value]),
    ))
    if existing:
        raise HTTPException(status_code=409, detail="双方已有待确认或有效合作")
    item = OperatorSupplierCooperation(
        operator_id=user.organization_id, supplier_id=payload.supplier_id,
        requested_by_user_id=user.id, categories=payload.categories, brands=payload.brands,
        sales_channels=payload.sales_channels, target_markets=payload.target_markets,
        message=(payload.message or "").strip() or None,
    )
    db.add(item)
    try:
        db.flush()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="双方已有待确认或有效合作") from error
    record_event(db, event_type="OPERATOR_COOPERATION_CREATED", entity_type="OperatorSupplierCooperation", entity_id=item.id, organization_id=user.organization_id, actor_type="USER", actor_id=user.id)
    db.commit(); db.refresh(item)
    return view(db, item)


@router.post("/{cooperation_id}/terminate", response_model=CooperationView)
def terminate(cooperation_id: str, db: DbSession, user: OperatorUser) -> CooperationView:
    item = db.scalar(select(OperatorSupplierCooperation).where(
        OperatorSupplierCooperation.id == cooperation_id,
        OperatorSupplierCooperation.operator_id == user.organization_id,
    ).with_for_update())
    if not item: raise HTTPException(status_code=404, detail="合作不存在")
    if item.status not in {CooperationStatus.PENDING.value, CooperationStatus.ACTIVE.value}:
        raise HTTPException(status_code=409, detail="当前合作不可终止")
    item.status = CooperationStatus.TERMINATED.value
    item.terminated_by_user_id = user.id; item.terminated_at = datetime.now(timezone.utc)
    binding = db.scalar(select(ErpBinding).where(ErpBinding.cooperation_id == item.id))
    if binding:
        binding.status = BindingStatus.INACTIVE.value; binding.unbound_at = item.terminated_at
    record_event(
        db, event_type="OPERATOR_COOPERATION_TERMINATED",
        entity_type="OperatorSupplierCooperation", entity_id=item.id,
        organization_id=user.organization_id, actor_type="USER", actor_id=user.id,
        payload={"terminated_by": "OPERATOR"},
    )
    db.commit(); db.refresh(item)
    return view(db, item)
