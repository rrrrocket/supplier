from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProductCreate(BaseModel):
    name: str = Field(min_length=2, max_length=240)
    brand: str = Field(min_length=1, max_length=160)
    model: str | None = Field(default=None, max_length=120)
    category: str = Field(min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    attributes: dict[str, Any] = Field(default_factory=dict)
    status: str = "DRAFT"

    @field_validator("brand")
    @classmethod
    def normalize_brand(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("brand name is required")
        return value


class ProductView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    brand_id: str
    brand: str
    model: str | None
    category: str
    description: str | None
    attributes: dict[str, Any]
    status: str
    created_at: datetime
    updated_at: datetime
    offer_count: int = 0


class OfferCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str
    supplier_sku_code: str = Field(min_length=1, max_length=120)
    price: Decimal = Field(gt=0, max_digits=14, decimal_places=4)
    currency: str = Field(default="CNY", min_length=3, max_length=8)
    moq: int = Field(default=1, ge=1, le=10_000_000)
    stock_qty: int = Field(default=0, ge=0, le=1_000_000_000)
    lead_time_days: int = Field(default=3, ge=0, le=3650)
    fulfillment_mode: str = Field(default="PURCHASE", max_length=40)
    valid_until: date | None = None
    status: str = "DRAFT"
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.strip().upper()


class OfferUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    price: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=4)
    currency: str | None = Field(default=None, min_length=3, max_length=8)
    moq: int | None = Field(default=None, ge=1, le=10_000_000)
    stock_qty: int | None = Field(default=None, ge=0, le=1_000_000_000)
    lead_time_days: int | None = Field(default=None, ge=0, le=3650)
    fulfillment_mode: str | None = Field(default=None, max_length=40)
    valid_until: date | None = None
    status: str | None = None
    notes: str | None = Field(default=None, max_length=2000)


class OfferView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    supplier_sku_id: str
    supplier_sku_code: str
    product_id: str
    product_name: str
    brand_id: str
    brand: str
    commercial_mode: str | None
    model: str | None
    category: str
    price: Decimal
    currency: str
    moq: int
    stock_qty: int
    lead_time_days: int
    fulfillment_mode: str
    valid_until: date | None
    status: str
    notes: str | None
    updated_at: datetime


class ProductPage(BaseModel):
    items: list[ProductView]
    next_cursor: str | None


class OfferPage(BaseModel):
    items: list[OfferView]
    next_cursor: str | None
