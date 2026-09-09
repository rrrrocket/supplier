from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class CooperationCreate(BaseModel):
    supplier_id: str
    categories: list[str] = Field(default_factory=list, max_length=30)
    brands: list[str] = Field(default_factory=list, max_length=30)
    sales_channels: list[str] = Field(default_factory=list, max_length=30)
    target_markets: list[str] = Field(default_factory=list, max_length=30)
    message: str | None = Field(default=None, max_length=2000)

    @field_validator("categories", "brands", "sales_channels", "target_markets")
    @classmethod
    def normalize_list(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item.strip() for item in value if item.strip()))


class BindingView(BaseModel):
    id: str
    cooperation_id: str
    operator_id: str
    supplier_id: str
    status: str
    bound_at: datetime


class CooperationView(BaseModel):
    id: str
    operator_id: str
    supplier_id: str
    status: str
    categories: list[str]
    brands: list[str]
    sales_channels: list[str]
    target_markets: list[str]
    message: str | None
    response_notes: str | None
    created_at: datetime
    binding: BindingView | None = None


class CooperationResponse(BaseModel):
    notes: str | None = Field(default=None, max_length=2000)
