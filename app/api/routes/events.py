from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.api.deps import DbSession, SupplierUser
from app.models.entities import EventLog
from app.schemas.dashboard import EventView


router = APIRouter(prefix="/events", tags=["事件审计"])


@router.get("", response_model=list[EventView])
def list_events(
    db: DbSession,
    user: SupplierUser,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[EventView]:
    events = db.scalars(
        select(EventLog)
        .where(EventLog.organization_id == user.organization_id)
        .order_by(EventLog.occurred_at.desc())
        .limit(limit)
    ).all()
    return [
        EventView(
            id=event.id,
            event_type=event.event_type,
            entity_type=event.entity_type,
            entity_id=event.entity_id,
            payload=event.payload,
            occurred_at=event.occurred_at,
        )
        for event in events
    ]
