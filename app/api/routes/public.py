from __future__ import annotations

from datetime import datetime, timezone
from secrets import token_hex

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.api.deps import DbSession
from app.models.entities import OperatorApplication, SupplierApplication, SupplierStatus
from app.schemas.operator import OperatorApplicationCreate, OperatorApplicationCreated
from app.schemas.supplier import SupplierApplicationCreate, SupplierApplicationCreated
from app.services.events import record_event


router = APIRouter(prefix="/public", tags=["公开接口"])


def make_application_no() -> str:
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"SUP-{day}-{token_hex(3).upper()}"


def make_operator_application_no() -> str:
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"OPR-{day}-{token_hex(3).upper()}"


@router.post(
    "/operator-applications",
    response_model=OperatorApplicationCreated,
    status_code=status.HTTP_201_CREATED,
)
def create_operator_application(
    payload: OperatorApplicationCreate, db: DbSession
) -> OperatorApplicationCreated:
    email = str(payload.email).lower()
    duplicate = db.scalar(
        select(OperatorApplication).where(
            func.lower(OperatorApplication.email) == email,
            OperatorApplication.status == SupplierStatus.PENDING.value,
        )
    )
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="该邮箱已有待审核的运营商申请")
    application = OperatorApplication(
        application_no=make_operator_application_no(),
        contact_name=payload.contact_name.strip(), phone=payload.phone.strip(), email=email,
        company_name=payload.company_name,
        unified_social_credit_code=payload.unified_social_credit_code,
        operator_type=payload.operator_type, province=payload.province, city=payload.city,
        website=payload.website, erp_name=payload.erp_name,
        sales_channels=payload.sales_channels, categories=payload.categories,
        target_markets=payload.target_markets, qualification_files=payload.qualification_files,
        message=payload.message, status=SupplierStatus.PENDING.value,
    )
    db.add(application)
    db.flush()
    record_event(
        db, event_type="OPERATOR_APPLICATION_CREATED", entity_type="OperatorApplication",
        entity_id=application.id, organization_id=None, actor_type="PUBLIC",
        payload={"application_no": application.application_no},
    )
    db.commit()
    return OperatorApplicationCreated(
        id=application.id, application_no=application.application_no,
        status=application.status, message="申请已提交，平台审核通过后将创建运营商账户。",
    )


@router.post(
    "/applications",
    response_model=SupplierApplicationCreated,
    status_code=status.HTTP_201_CREATED,
)
def create_application(
    payload: SupplierApplicationCreate,
    db: DbSession,
) -> SupplierApplicationCreated:
    application = SupplierApplication(
        application_no=make_application_no(),
        company_name=payload.company_name.strip(),
        unified_social_credit_code=(payload.unified_social_credit_code or "").strip() or None,
        company_type=payload.company_type.strip(),
        province=payload.province.strip(),
        city=payload.city.strip(),
        contact_name=payload.contact_name.strip(),
        phone=payload.phone.strip(),
        email=str(payload.email).lower(),
        categories=payload.categories,
        cooperation_modes=payload.cooperation_modes,
        annual_revenue_range=payload.annual_revenue_range,
        supports_dropshipping=payload.supports_dropshipping,
        supports_oem=payload.supports_oem,
        has_export_experience=payload.has_export_experience,
        message=(payload.message or "").strip() or None,
        status=SupplierStatus.PENDING.value,
    )
    db.add(application)
    db.flush()
    record_event(
        db,
        event_type="SUPPLIER_APPLICATION_CREATED",
        entity_type="SupplierApplication",
        entity_id=application.id,
        organization_id=None,
        actor_type="PUBLIC",
        payload={
            "application_no": application.application_no,
            "company_name": application.company_name,
        },
    )
    db.commit()
    return SupplierApplicationCreated(
        id=application.id,
        application_no=application.application_no,
        status=application.status,
        message="申请已提交。平台审核后将通过你填写的联系方式与你确认合作方案。",
    )
