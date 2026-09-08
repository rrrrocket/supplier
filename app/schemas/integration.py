from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


IntegrationScope = Literal[
    "suppliers:read",
    "supplier-brands:read",
    "supplier-skus:read",
    "supplier-costs:read",
]


class IntegrationClientCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    scopes: list[IntegrationScope] = Field(min_length=1)
    expires_at: AwareDatetime | None = None


class IntegrationClientView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    token_prefix: str
    scopes: list[IntegrationScope]
    expires_at: datetime | None
    is_active: bool
    last_used_at: datetime | None


class IntegrationClientCredential(IntegrationClientView):
    token: str
