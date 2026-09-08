from __future__ import annotations

from datetime import datetime
from decimal import Decimal
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


class SupplierIntegrationView(BaseModel):
    supplier_id: str
    supplier_code: str
    supplier_name: str
    status: str
    updated_at: datetime


class SupplierBrandIntegrationView(BaseModel):
    brand_id: str
    brand_code: str
    brand_name: str
    commercial_mode: str
    status: str
    updated_at: datetime


class SupplierSkuIntegrationView(BaseModel):
    supplier_sku_id: str
    supplier_sku_code: str
    brand_id: str
    brand_name: str
    product_name: str
    model: str | None
    manufacturer_part_number: str | None
    barcode: str | None
    commercial_mode: str | None
    status: str
    updated_at: datetime


class SupplierIntegrationPage(BaseModel):
    items: list[SupplierIntegrationView]
    next_cursor: str | None


class SupplierBrandIntegrationPage(BaseModel):
    items: list[SupplierBrandIntegrationView]
    next_cursor: str | None


class SupplierSkuIntegrationPage(BaseModel):
    items: list[SupplierSkuIntegrationView]
    next_cursor: str | None


class CurrentSkuCostView(BaseModel):
    supplier_id: str
    supplier_sku_id: str
    supplier_sku_code: str
    cost_price: Decimal
    currency: str
    cost_updated_at: datetime


class SkuCostQueryItem(BaseModel):
    client_sku_id: str = Field(min_length=1, max_length=200)
    supplier_id: str
    supplier_sku_id: str


class SkuCostBatchRequest(BaseModel):
    items: list[SkuCostQueryItem] = Field(min_length=1, max_length=500)


class SkuCostBatchSuccess(CurrentSkuCostView):
    client_sku_id: str
    status: Literal["OK"] = "OK"


class SkuCostBatchError(BaseModel):
    client_sku_id: str
    supplier_id: str
    supplier_sku_id: str
    status: Literal["ERROR"] = "ERROR"
    error_code: str
    message: str


class SkuCostBatchResponse(BaseModel):
    items: list[SkuCostBatchSuccess | SkuCostBatchError]
