from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class BrandCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    code: str | None = Field(default=None, max_length=60)
    aliases: list[str] = Field(default_factory=list)


class BrandView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    code: str
    name: str
    status: str
    updated_at: datetime


class CooperationUpdate(BaseModel):
    commercial_mode: Literal["SELF_PURCHASE", "JOINT_OPERATION", "B2B"]


class CooperationView(BaseModel):
    id: str
    supplier_id: str
    brand_id: str
    brand_name: str
    commercial_mode: str | None
    status: str
    valid_from: date | None
    valid_to: date | None
    updated_at: datetime


class SupplierBrandCooperationView(BaseModel):
    brand_id: str
    brand_code: str
    brand_name: str
    commercial_mode: str | None
    status: str
