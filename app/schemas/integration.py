from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator


class IntegrationScope(str, Enum):
    SUPPLIERS_READ = "suppliers:read"
    SUPPLIER_BRANDS_READ = "supplier-brands:read"
    SUPPLIER_SKUS_READ = "supplier-skus:read"
    SUPPLIER_COSTS_READ = "supplier-costs:read"


INTEGRATION_SCOPES = tuple(scope.value for scope in IntegrationScope)


class SkuCostErrorCode(str, Enum):
    SUPPLIER_NOT_FOUND = "SUPPLIER_NOT_FOUND"
    SUPPLIER_INACTIVE = "SUPPLIER_INACTIVE"
    SKU_NOT_FOUND = "SKU_NOT_FOUND"
    SKU_INACTIVE = "SKU_INACTIVE"
    SKU_SUPPLIER_MISMATCH = "SKU_SUPPLIER_MISMATCH"
    BRAND_COOPERATION_INACTIVE = "BRAND_COOPERATION_INACTIVE"
    NOT_SELF_PURCHASE = "NOT_SELF_PURCHASE"
    COST_PRICE_MISSING = "COST_PRICE_MISSING"


SKU_COST_ERROR_CODES = tuple(code.value for code in SkuCostErrorCode)


class IntegrationClientCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    scopes: list[IntegrationScope] = Field(min_length=1)
    expires_at: AwareDatetime | None = None

    @field_validator("expires_at")
    @classmethod
    def expiration_must_be_future(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.astimezone(timezone.utc) <= datetime.now(timezone.utc):
            raise ValueError("expires_at must be in the future")
        return value


class IntegrationClientView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    client_type: str
    owner_organization_id: str | None
    token_prefix: str
    scopes: list[IntegrationScope]
    expires_at: datetime | None
    is_active: bool
    last_used_at: datetime | None


class IntegrationClientCredential(IntegrationClientView):
    token: str


class IntegrationClientPage(BaseModel):
    items: list[IntegrationClientView]
    total: int
    page: int
    page_size: int


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
    commercial_mode: str | None
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
    sync_watermark: datetime


class SupplierBrandIntegrationPage(BaseModel):
    items: list[SupplierBrandIntegrationView]
    next_cursor: str | None
    sync_watermark: datetime


class SupplierSkuIntegrationPage(BaseModel):
    items: list[SupplierSkuIntegrationView]
    next_cursor: str | None
    sync_watermark: datetime


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
    error_code: SkuCostErrorCode
    message: str


class SkuCostBatchResponse(BaseModel):
    items: list[SkuCostBatchSuccess | SkuCostBatchError]
