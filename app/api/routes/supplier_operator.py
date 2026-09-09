from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from app.api.deps import DbSession, SupplierUser
from app.models.entities import BindingStatus, CooperationStatus, ErpBinding, OperatorSupplierCooperation
from app.schemas.cooperation import CooperationPage, CooperationResponse, CooperationView
from app.api.routes.operator_cooperations import view
from app.services.events import record_event


router = APIRouter(prefix="/supplier-operator/cooperations", tags=["供应商运营商合作"])


@router.get("", response_model=CooperationPage)
def list_cooperations(
    db: DbSession, user: SupplierUser, page: int = Query(1, ge=1),
    page_size: int = Query(50),
) -> CooperationPage:
    if page_size not in {20, 50, 100, 200}:
        raise HTTPException(status_code=422, detail="页面行数仅支持 20、50、100 或 200")
    condition = OperatorSupplierCooperation.supplier_id == user.organization_id
    total = db.scalar(select(func.count(OperatorSupplierCooperation.id)).where(condition)) or 0
    items = db.scalars(select(OperatorSupplierCooperation).where(condition)
        .order_by(OperatorSupplierCooperation.created_at.desc())
        .offset((page-1)*page_size).limit(page_size)).all()
    return CooperationPage(items=[view(db, item) for item in items], total=total, page=page, page_size=page_size)


def pending(db: DbSession, cooperation_id: str, supplier_id: str) -> OperatorSupplierCooperation:
    item = db.scalar(select(OperatorSupplierCooperation).where(
        OperatorSupplierCooperation.id == cooperation_id,
        OperatorSupplierCooperation.supplier_id == supplier_id,
    ).with_for_update())
    if not item: raise HTTPException(status_code=404, detail="合作不存在")
    if item.status != CooperationStatus.PENDING.value:
        raise HTTPException(status_code=409, detail="合作已处理")
    return item


@router.post("/{cooperation_id}/accept", response_model=CooperationView)
def accept(cooperation_id: str, payload: CooperationResponse, db: DbSession, user: SupplierUser) -> CooperationView:
    item = pending(db, cooperation_id, user.organization_id)
    now = datetime.now(timezone.utc)
    item.status = CooperationStatus.ACTIVE.value; item.response_notes = payload.notes
    item.responded_by_user_id = user.id; item.responded_at = now
    db.add(ErpBinding(cooperation_id=item.id, operator_id=item.operator_id, supplier_id=item.supplier_id, bound_at=now))
    record_event(
        db, event_type="OPERATOR_COOPERATION_ACCEPTED",
        entity_type="OperatorSupplierCooperation", entity_id=item.id,
        organization_id=user.organization_id, actor_type="USER", actor_id=user.id,
    )
    db.commit(); db.refresh(item)
    return view(db, item)


@router.post("/{cooperation_id}/reject", response_model=CooperationView)
def reject(cooperation_id: str, payload: CooperationResponse, db: DbSession, user: SupplierUser) -> CooperationView:
    item = pending(db, cooperation_id, user.organization_id)
    item.status = CooperationStatus.REJECTED.value; item.response_notes = payload.notes
    item.responded_by_user_id = user.id; item.responded_at = datetime.now(timezone.utc)
    record_event(
        db, event_type="OPERATOR_COOPERATION_REJECTED",
        entity_type="OperatorSupplierCooperation", entity_id=item.id,
        organization_id=user.organization_id, actor_type="USER", actor_id=user.id,
    )
    db.commit(); db.refresh(item)
    return view(db, item)


@router.post("/{cooperation_id}/terminate", response_model=CooperationView)
def terminate(cooperation_id: str, db: DbSession, user: SupplierUser) -> CooperationView:
    item = db.scalar(select(OperatorSupplierCooperation).where(
        OperatorSupplierCooperation.id == cooperation_id,
        OperatorSupplierCooperation.supplier_id == user.organization_id,
    ).with_for_update())
    if not item:
        raise HTTPException(status_code=404, detail="合作不存在")
    if item.status != CooperationStatus.ACTIVE.value:
        raise HTTPException(status_code=409, detail="只有有效合作可以终止")
    now = datetime.now(timezone.utc)
    item.status = CooperationStatus.TERMINATED.value
    item.terminated_by_user_id = user.id
    item.terminated_at = now
    binding = db.scalar(select(ErpBinding).where(ErpBinding.cooperation_id == item.id))
    if binding:
        binding.status = BindingStatus.INACTIVE.value
        binding.unbound_at = now
    record_event(
        db, event_type="OPERATOR_COOPERATION_TERMINATED",
        entity_type="OperatorSupplierCooperation", entity_id=item.id,
        organization_id=user.organization_id, actor_type="USER", actor_id=user.id,
        payload={"terminated_by": "SUPPLIER"},
    )
    db.commit()
    db.refresh(item)
    return view(db, item)
