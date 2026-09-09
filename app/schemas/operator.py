from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator


class OperatorApplicationCreate(BaseModel):
    contact_name: str = Field(min_length=2, max_length=100)
    phone: str = Field(min_length=6, max_length=60)
    email: EmailStr
    company_name: str | None = Field(default=None, max_length=240)
    unified_social_credit_code: str | None = Field(default=None, max_length=40)
    operator_type: str | None = Field(default=None, max_length=80)
    province: str | None = Field(default=None, max_length=80)
    city: str | None = Field(default=None, max_length=80)
    website: str | None = Field(default=None, max_length=255)
    erp_name: str | None = Field(default=None, max_length=120)
    sales_channels: list[str] = Field(default_factory=list, max_length=30)
    categories: list[str] = Field(default_factory=list, max_length=30)
    target_markets: list[str] = Field(default_factory=list, max_length=30)
    qualification_files: list[str] = Field(default_factory=list, max_length=20)
    message: str | None = Field(default=None, max_length=2000)

    @field_validator("contact_name", "phone", mode="before")
    @classmethod
    def required_text(cls, value: object) -> object:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("必填字段不能为空")
        return value.strip()

    @field_validator(
        "company_name", "unified_social_credit_code", "operator_type", "province", "city",
        "website", "erp_name", "message", mode="before",
    )
    @classmethod
    def blank_to_none(cls, value: object) -> object:
        return value.strip() or None if isinstance(value, str) else value

    @field_validator("sales_channels", "categories", "target_markets", "qualification_files")
    @classmethod
    def normalize_list(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item.strip() for item in value if item.strip()))


class OperatorApplicationCreated(BaseModel):
    id: str
    application_no: str
    status: str
    message: str


class OperatorApplicationAdminView(BaseModel):
    id: str
    application_no: str
    contact_name: str
    phone: str
    email: EmailStr
    company_name: str | None
    unified_social_credit_code: str | None
    operator_type: str | None
    province: str | None
    city: str | None
    website: str | None
    erp_name: str | None
    sales_channels: list[str]
    categories: list[str]
    target_markets: list[str]
    qualification_files: list[str]
    message: str | None
    status: str
    review_notes: str | None
    approved_organization_id: str | None
    created_at: datetime
    reviewed_at: datetime | None


class OperatorProfileView(BaseModel):
    id: str
    organization_id: str
    company_name: str | None
    unified_social_credit_code: str | None
    operator_type: str | None
    province: str | None
    city: str | None
    contact_name: str
    contact_phone: str
    contact_email: EmailStr
    website: str | None
    erp_name: str | None
    sales_channels: list[str]
    categories: list[str]
    target_markets: list[str]
    qualification_files: list[str]


class OperatorProfileUpdate(BaseModel):
    contact_name: str | None = Field(default=None, min_length=2, max_length=100)
    contact_phone: str | None = Field(default=None, min_length=6, max_length=60)
    contact_email: EmailStr | None = None
    company_name: str | None = Field(default=None, max_length=240)
    unified_social_credit_code: str | None = Field(default=None, max_length=40)
    operator_type: str | None = Field(default=None, max_length=80)
    province: str | None = Field(default=None, max_length=80)
    city: str | None = Field(default=None, max_length=80)
    website: str | None = Field(default=None, max_length=255)
    erp_name: str | None = Field(default=None, max_length=120)
    sales_channels: list[str] | None = Field(default=None, max_length=30)
    categories: list[str] | None = Field(default=None, max_length=30)
    target_markets: list[str] | None = Field(default=None, max_length=30)
    qualification_files: list[str] | None = Field(default=None, max_length=20)

    @field_validator("contact_name", "contact_phone", "contact_email", mode="before")
    @classmethod
    def required_profile_text(cls, value: object) -> object:
        if value is None or not str(value).strip():
            raise ValueError("联系人、手机号和邮箱不能为空")
        return str(value).strip()

    @field_validator(
        "company_name", "unified_social_credit_code", "operator_type", "province", "city",
        "website", "erp_name", mode="before",
    )
    @classmethod
    def optional_profile_text(cls, value: object) -> object:
        return value.strip() or None if isinstance(value, str) else value

    @field_validator("sales_channels", "categories", "target_markets", "qualification_files")
    @classmethod
    def normalize_optional_list(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return list(dict.fromkeys(item.strip() for item in value if item.strip()))


class OperatorDashboardView(BaseModel):
    available_suppliers: int
    pending_cooperations: int
    active_cooperations: int
    active_bindings: int


class OperatorManagementView(BaseModel):
    organization_id: str
    organization_code: str
    organization_name: str
    is_active: bool
    contact_name: str
    contact_phone: str
    contact_email: EmailStr
    company_name: str | None
    operator_type: str | None
    erp_name: str | None
    created_at: datetime


class OperatorApplicationAdminPage(BaseModel):
    items: list[OperatorApplicationAdminView]
    total: int
    page: int
    page_size: int


class OperatorManagementPage(BaseModel):
    items: list[OperatorManagementView]
    total: int
    page: int
    page_size: int
