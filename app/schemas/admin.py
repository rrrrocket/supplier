from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class ApplicationAdminView(BaseModel):
    id: str
    application_no: str
    company_name: str
    unified_social_credit_code: str | None
    company_type: str
    province: str
    city: str
    contact_name: str
    phone: str
    email: EmailStr
    categories: list[str]
    cooperation_modes: list[str]
    annual_revenue_range: str | None
    supports_dropshipping: bool
    supports_oem: bool
    has_export_experience: bool
    message: str | None
    status: str
    review_notes: str | None
    approved_organization_id: str | None
    created_at: datetime
    reviewed_at: datetime | None


class ApplicationReviewRequest(BaseModel):
    notes: str | None = Field(default=None, max_length=2000)


class ApplicationApprovalResponse(BaseModel):
    application_id: str
    application_no: str
    status: str
    organization_id: str
    organization_code: str
    login_email: EmailStr
    temporary_password: str
    message: str


class SupplierManagementView(BaseModel):
    organization_id: str
    organization_code: str
    organization_name: str
    legal_name: str
    status: str
    profile_completion: int
    contact_name: str | None
    contact_email: str | None
    product_count: int
    active_offer_count: int
    created_at: datetime
