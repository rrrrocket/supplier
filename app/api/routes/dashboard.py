from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import DbSession, SupplierUser
from app.schemas.dashboard import DashboardResponse
from app.services.dashboard import build_dashboard


router = APIRouter(prefix="/dashboard", tags=["供应商看板"])


@router.get("", response_model=DashboardResponse)
def get_dashboard(db: DbSession, user: SupplierUser) -> DashboardResponse:
    dashboard = build_dashboard(
        db,
        organization_id=user.organization_id,
        organization_name=user.organization.name,
    )
    db.commit()
    return dashboard
