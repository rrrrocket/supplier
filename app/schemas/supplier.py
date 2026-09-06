from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field, field_validator


class SupplierApplicationCreate(BaseModel):
    company_name: str = Field(min_length=2, max_length=240)
    unified_social_credit_code: str | None = Field(default=None, max_length=40)
    company_type: str = Field(min_length=2, max_length=40)
    province: str = Field(min_length=1, max_length=80)
    city: str = Field(min_length=1, max_length=80)
    contact_name: str = Field(min_length=2, max_length=100)
    phone: str = Field(min_length=6, max_length=60)
    email: EmailStr
    categories: list[str] = Field(min_length=1, max_length=20)
    cooperation_modes: list[str] = Field(min_length=1, max_length=10)
    annual_revenue_range: str | None = Field(default=None, max_length=60)
    supports_dropshipping: bool = False
    supports_oem: bool = False
    has_export_experience: bool = False
    message: str | None = Field(default=None, max_length=2000)

    @field_validator("categories", "cooperation_modes")
    @classmethod
    def strip_list_values(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item.strip()]
        if not cleaned:
            raise ValueError("至少选择一项")
        return list(dict.fromkeys(cleaned))


class SupplierApplicationCreated(BaseModel):
    id: str
    application_no: str
    status: str
    message: str


class SupplierProfileView(BaseModel):
    id: str
    legal_name: str
    unified_social_credit_code: str | None
    supplier_type: str
    province: str | None
    city: str | None
    address: str | None
    contact_name: str | None
    contact_phone: str | None
    contact_email: str | None
    website: str | None
    categories: list[str]
    cooperation_modes: list[str]
    export_markets: list[str]
    supports_dropshipping: bool
    supports_oem: bool
    has_export_experience: bool
    status: str
    profile_completion: int


class SupplierProfileUpdate(BaseModel):
    legal_name: str | None = Field(default=None, min_length=2, max_length=240)
    unified_social_credit_code: str | None = Field(default=None, max_length=40)
    supplier_type: str | None = Field(default=None, max_length=40)
    province: str | None = Field(default=None, max_length=80)
    city: str | None = Field(default=None, max_length=80)
    address: str | None = Field(default=None, max_length=300)
    contact_name: str | None = Field(default=None, max_length=100)
    contact_phone: str | None = Field(default=None, max_length=60)
    contact_email: EmailStr | None = None
    website: str | None = Field(default=None, max_length=255)
    categories: list[str] | None = Field(default=None, max_length=20)
    cooperation_modes: list[str] | None = Field(default=None, max_length=10)
    export_markets: list[str] | None = Field(default=None, max_length=30)
    supports_dropshipping: bool | None = None
    supports_oem: bool | None = None
    has_export_experience: bool | None = None
