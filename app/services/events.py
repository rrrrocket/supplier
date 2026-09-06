from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.entities import EventLog


def record_event(
    db: Session,
    *,
    event_type: str,
    entity_type: str,
    entity_id: str | None,
    organization_id: str | None,
    actor_type: str = "SYSTEM",
    actor_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> EventLog:
    event = EventLog(
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        organization_id=organization_id,
        actor_type=actor_type,
        actor_id=actor_id,
        payload=payload or {},
    )
    db.add(event)
    return event
