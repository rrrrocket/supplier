from __future__ import annotations

from pydantic import BaseModel


class SupplierDirectoryItem(BaseModel):
    supplier_id: str
    supplier_code: str
    supplier_name: str
    legal_name: str
    supplier_type: str
    province: str | None
    city: str | None
    website: str | None
    categories: list[str]
    cooperation_modes: list[str]
    supports_dropshipping: bool
    supports_oem: bool
    has_export_experience: bool
    product_count: int
    active_offer_count: int
    contact_name: str | None
    contact_phone: str | None
    contact_email: str | None


class SupplierDirectoryPage(BaseModel):
    items: list[SupplierDirectoryItem]
    total: int
    page: int
    page_size: int


class OperatorDirectoryItem(BaseModel):
    operator_id: str
    operator_code: str
    operator_name: str
    company_name: str | None
    operator_type: str | None
    province: str | None
    city: str | None
    website: str | None
    erp_name: str | None
    sales_channels: list[str]
    categories: list[str]
    target_markets: list[str]
    contact_name: str | None
    contact_phone: str | None
    contact_email: str | None


class OperatorDirectoryPage(BaseModel):
    items: list[OperatorDirectoryItem]
    total: int
    page: int
    page_size: int
