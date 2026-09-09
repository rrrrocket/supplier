from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.deps import DbSession, SupplierUser
from app.models.entities import CooperationStatus, ErpBinding, OperatorSupplierCooperation
from app.schemas.cooperation import CooperationResponse, CooperationView
from app.api.routes.operator_cooperations import view


router = APIRouter(prefix="/supplier-operator/cooperations", tags=["供应商运营商合作"])


@router.get("", response_model=list[CooperationView])
def list_cooperations(db: DbSession, user: SupplierUser) -> list[CooperationView]:
    items = db.scalars(select(OperatorSupplierCooperation).where(
        OperatorSupplierCooperation.supplier_id == user.organization_id
    ).order_by(OperatorSupplierCooperation.created_at.desc())).all()
    return [view(db, item) for item in items]


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
    db.commit(); db.refresh(item)
    return view(db, item)


@router.post("/{cooperation_id}/reject", response_model=CooperationView)
def reject(cooperation_id: str, payload: CooperationResponse, db: DbSession, user: SupplierUser) -> CooperationView:
    item = pending(db, cooperation_id, user.organization_id)
    item.status = CooperationStatus.REJECTED.value; item.response_notes = payload.notes
    item.responded_by_user_id = user.id; item.responded_at = datetime.now(timezone.utc)
    db.commit(); db.refresh(item)
    return view(db, item)
