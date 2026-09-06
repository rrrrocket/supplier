from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class MetricCard(BaseModel):
    key: str
    label: str
    value: int | float | str
    hint: str
    tone: str = "neutral"


class ChecklistItem(BaseModel):
    key: str
    label: str
    description: str
    completed: bool
    action_hash: str


class EventView(BaseModel):
    id: str
    event_type: str
    entity_type: str
    entity_id: str | None
    payload: dict[str, Any]
    occurred_at: datetime


class DashboardResponse(BaseModel):
    organization_name: str
    supplier_status: str
    profile_completion: int
    metrics: list[MetricCard]
    checklist: list[ChecklistItem]
    recent_events: list[EventView]
