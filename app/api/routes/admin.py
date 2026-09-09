from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentUser, DbSession
from app.core.security import hash_password
from app.models.entities import (
    OfferStatus,
    OperatorApplication,
    OperatorProfile,
    OperatorSupplierCooperation,
    Organization,
    OrganizationType,
    Product,
    SupplierApplication,
    SupplierOffer,
    SupplierProfile,
    SupplierStatus,
    User,
    UserRole,
)
from app.schemas.admin import (
    ApplicationAdminView,
    ApplicationApprovalResponse,
    ApplicationReviewRequest,
    SupplierManagementView,
)
from app.schemas.cooperation import CooperationPage, CooperationView
from app.schemas.operator import (
    OperatorApplicationAdminPage, OperatorApplicationAdminView,
    OperatorManagementPage, OperatorManagementSummary, OperatorManagementView,
)
from app.api.routes.operator_cooperations import view as cooperation_view
from app.services.events import record_event
from app.services.scoring import calculate_profile_completion


router = APIRouter(prefix="/admin", tags=["平台管理"])
OPERATOR_APPLICATION_STATUSES = {
    SupplierStatus.PENDING.value,
    SupplierStatus.APPROVED.value,
    SupplierStatus.REJECTED.value,
}
LIKE_ESCAPE = "\\"


def require_platform_admin(user: CurrentUser) -> User:
    if (
        user.role != UserRole.PLATFORM_ADMIN.value
        or user.organization.organization_type != OrganizationType.PLATFORM.value
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要平台管理员权限")
    return user


PlatformAdmin = Annotated[User, Depends(require_platform_admin)]


def application_view(item: SupplierApplication) -> ApplicationAdminView:
    return ApplicationAdminView(
        id=item.id,
        application_no=item.application_no,
        company_name=item.company_name,
        unified_social_credit_code=item.unified_social_credit_code,
        company_type=item.company_type,
        province=item.province,
        city=item.city,
        contact_name=item.contact_name,
        phone=item.phone,
        email=item.email,
        categories=item.categories,
        cooperation_modes=item.cooperation_modes,
        annual_revenue_range=item.annual_revenue_range,
        supports_dropshipping=item.supports_dropshipping,
        supports_oem=item.supports_oem,
        has_export_experience=item.has_export_experience,
        message=item.message,
        status=item.status,
        review_notes=item.review_notes,
        approved_organization_id=item.approved_organization_id,
        created_at=item.created_at,
        reviewed_at=item.reviewed_at,
    )


def generate_org_code(application: SupplierApplication) -> str:
    return f"SUP-{application.application_no.rsplit('-', 1)[-1]}"


def generate_temporary_password() -> str:
    return f"M1-{secrets.token_urlsafe(8)}-A9"


def normalize_supplier_type(company_type: str) -> str:
    mapping = {
        "生产工厂": "FACTORY",
        "工贸一体": "FACTORY_TRADER",
        "品牌方": "BRAND",
        "贸易商/经销商": "TRADER",
        "贸易商": "TRADER",
        "经销商": "TRADER",
    }
    return mapping.get(company_type.strip(), "OTHER")


def operator_application_view(item: OperatorApplication) -> OperatorApplicationAdminView:
    return OperatorApplicationAdminView(
        id=item.id, application_no=item.application_no, contact_name=item.contact_name,
        phone=item.phone, email=item.email, company_name=item.company_name,
        unified_social_credit_code=item.unified_social_credit_code,
        operator_type=item.operator_type, province=item.province, city=item.city,
        website=item.website, erp_name=item.erp_name, sales_channels=item.sales_channels,
        categories=item.categories, target_markets=item.target_markets,
        qualification_files=item.qualification_files, message=item.message,
        status=item.status, review_notes=item.review_notes,
        approved_organization_id=item.approved_organization_id,
        created_at=item.created_at, reviewed_at=item.reviewed_at,
    )


def normalized_keyword_pattern(keyword: str | None) -> str | None:
    normalized = (keyword or "").strip().lower()
    if not normalized:
        return None
    escaped = (
        normalized.replace(LIKE_ESCAPE, LIKE_ESCAPE * 2)
        .replace("%", f"{LIKE_ESCAPE}%")
        .replace("_", f"{LIKE_ESCAPE}_")
    )
    return f"%{escaped}%"


def normalized_legacy_operator_status(value: str | None) -> str | None:
    normalized = (value or "").strip().upper()
    if not normalized:
        return None
    if normalized not in OPERATOR_APPLICATION_STATUSES:
        raise HTTPException(status_code=422, detail="status 参数无效")
    return normalized


@router.get("/operator-summary", response_model=OperatorManagementSummary)
def operator_management_summary(
    db: DbSession,
    _: PlatformAdmin,
) -> OperatorManagementSummary:
    pending_applications = db.scalar(
        select(func.count(OperatorApplication.id)).where(
            OperatorApplication.status == SupplierStatus.PENDING.value
        )
    ) or 0
    approved_applications = db.scalar(
        select(func.count(OperatorApplication.id)).where(
            OperatorApplication.status == SupplierStatus.APPROVED.value
        )
    ) or 0
    active_operators = db.scalar(
        select(func.count(Organization.id)).where(
            Organization.organization_type == OrganizationType.OPERATOR.value,
            Organization.is_active.is_(True),
        )
    ) or 0
    return OperatorManagementSummary(
        pending_applications=pending_applications,
        approved_applications=approved_applications,
        active_operators=active_operators,
    )


@router.get("/operator-applications", response_model=OperatorApplicationAdminPage)
def list_operator_applications(
    db: DbSession,
    _: PlatformAdmin,
    keyword: str | None = Query(default=None, max_length=200),
    application_status: str | None = Query(
        default=None,
        alias="status",
        max_length=30,
    ),
    status_filter: Literal["PENDING", "APPROVED", "REJECTED"] | None = Query(
        default=None
    ),
    page: int = Query(1, ge=1), page_size: int = Query(50),
) -> OperatorApplicationAdminPage:
    if page_size not in {20, 50, 100, 200}:
        raise HTTPException(status_code=422, detail="页面行数仅支持 20、50、100 或 200")
    stmt = select(OperatorApplication).order_by(
        OperatorApplication.created_at.desc(), OperatorApplication.id.desc()
    )
    keyword_pattern = normalized_keyword_pattern(keyword)
    if keyword_pattern:
        stmt = stmt.where(or_(
            func.lower(OperatorApplication.contact_name).like(
                keyword_pattern, escape=LIKE_ESCAPE
            ),
            func.lower(OperatorApplication.phone).like(
                keyword_pattern, escape=LIKE_ESCAPE
            ),
            func.lower(OperatorApplication.email).like(
                keyword_pattern, escape=LIKE_ESCAPE
            ),
            func.lower(OperatorApplication.company_name).like(
                keyword_pattern, escape=LIKE_ESCAPE
            ),
            func.lower(OperatorApplication.application_no).like(
                keyword_pattern, escape=LIKE_ESCAPE
            ),
            func.lower(OperatorApplication.operator_type).like(
                keyword_pattern, escape=LIKE_ESCAPE
            ),
            func.lower(OperatorApplication.erp_name).like(
                keyword_pattern, escape=LIKE_ESCAPE
            ),
        ))
    legacy_status = normalized_legacy_operator_status(application_status)
    if legacy_status and status_filter and legacy_status != status_filter:
        raise HTTPException(status_code=422, detail="status 与 status_filter 不能冲突")
    effective_status = status_filter or legacy_status
    if effective_status:
        stmt = stmt.where(OperatorApplication.status == effective_status)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    items = db.scalars(stmt.offset((page-1)*page_size).limit(page_size)).all()
    return OperatorApplicationAdminPage(
        items=[operator_application_view(item) for item in items], total=total,
        page=page, page_size=page_size,
    )


@router.get("/operators", response_model=OperatorManagementPage)
def list_operators(
    db: DbSession, _: PlatformAdmin,
    keyword: str | None = Query(default=None, max_length=200),
    page: int = Query(1, ge=1),
    page_size: int = Query(50),
) -> OperatorManagementPage:
    if page_size not in {20, 50, 100, 200}:
        raise HTTPException(status_code=422, detail="页面行数仅支持 20、50、100 或 200")
    stmt = (select(Organization, OperatorProfile)
        .join(OperatorProfile, OperatorProfile.organization_id == Organization.id)
        .where(Organization.organization_type == OrganizationType.OPERATOR.value)
        .order_by(Organization.created_at.desc(), Organization.id.desc()))
    keyword_pattern = normalized_keyword_pattern(keyword)
    if keyword_pattern:
        stmt = stmt.where(or_(
            func.lower(Organization.name).like(keyword_pattern, escape=LIKE_ESCAPE),
            func.lower(Organization.code).like(keyword_pattern, escape=LIKE_ESCAPE),
            func.lower(OperatorProfile.contact_name).like(
                keyword_pattern, escape=LIKE_ESCAPE
            ),
            func.lower(OperatorProfile.contact_email).like(
                keyword_pattern, escape=LIKE_ESCAPE
            ),
            func.lower(OperatorProfile.contact_phone).like(
                keyword_pattern, escape=LIKE_ESCAPE
            ),
            func.lower(OperatorProfile.operator_type).like(
                keyword_pattern, escape=LIKE_ESCAPE
            ),
            func.lower(OperatorProfile.erp_name).like(
                keyword_pattern, escape=LIKE_ESCAPE
            ),
        ))
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = db.execute(stmt.offset((page-1)*page_size).limit(page_size)).all()
    items = [OperatorManagementView(
        organization_id=organization.id, organization_code=organization.code,
        organization_name=organization.name, is_active=organization.is_active,
        contact_name=profile.contact_name, contact_phone=profile.contact_phone,
        contact_email=profile.contact_email, company_name=profile.company_name,
        operator_type=profile.operator_type, erp_name=profile.erp_name,
        created_at=organization.created_at,
    ) for organization, profile in rows]
    return OperatorManagementPage(items=items, total=total, page=page, page_size=page_size)


@router.get("/operator-cooperations", response_model=CooperationPage)
def list_operator_cooperations(
    db: DbSession, _: PlatformAdmin, page: int = Query(1, ge=1),
    page_size: int = Query(50),
) -> CooperationPage:
    if page_size not in {20, 50, 100, 200}:
        raise HTTPException(status_code=422, detail="页面行数仅支持 20、50、100 或 200")
    total = db.scalar(select(func.count(OperatorSupplierCooperation.id))) or 0
    items = db.scalars(select(OperatorSupplierCooperation).order_by(
        OperatorSupplierCooperation.created_at.desc(), OperatorSupplierCooperation.id.desc()
    ).offset((page-1)*page_size).limit(page_size)).all()
    return CooperationPage(
        items=[cooperation_view(db, item) for item in items], total=total,
        page=page, page_size=page_size,
    )


@router.post(
    "/operator-applications/{application_id}/approve",
    response_model=ApplicationApprovalResponse,
)
def approve_operator_application(
    application_id: str,
    payload: ApplicationReviewRequest,
    db: DbSession,
    admin: PlatformAdmin,
) -> ApplicationApprovalResponse:
    application = db.get(OperatorApplication, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="申请不存在")
    if application.status != SupplierStatus.PENDING.value:
        raise HTTPException(status_code=409, detail="只有待审核申请可以通过")
    if db.scalar(select(User).where(func.lower(User.email) == application.email.lower())):
        raise HTTPException(status_code=409, detail="该邮箱已经关联现有账号")
    if application.unified_social_credit_code and db.scalar(select(OperatorProfile).where(
        OperatorProfile.unified_social_credit_code == application.unified_social_credit_code
    )):
        raise HTTPException(status_code=409, detail="该统一社会信用代码已关联运营商组织")

    code = f"OPR-{application.application_no.rsplit('-', 1)[-1]}"
    if db.scalar(select(Organization).where(Organization.code == code)):
        code = f"{code}-{secrets.token_hex(2).upper()}"
    organization = Organization(
        code=code,
        name=application.company_name or f"{application.contact_name}的运营团队",
        organization_type=OrganizationType.OPERATOR.value,
    )
    db.add(organization)
    db.flush()
    db.add(OperatorProfile(
        organization_id=organization.id, company_name=application.company_name,
        unified_social_credit_code=application.unified_social_credit_code,
        operator_type=application.operator_type, province=application.province,
        city=application.city, contact_name=application.contact_name,
        contact_phone=application.phone, contact_email=application.email,
        website=application.website, erp_name=application.erp_name,
        sales_channels=application.sales_channels, categories=application.categories,
        target_markets=application.target_markets,
        qualification_files=application.qualification_files,
    ))
    temporary_password = generate_temporary_password()
    user = User(
        organization_id=organization.id, email=application.email.lower(),
        name=application.contact_name, role=UserRole.OPERATOR.value,
        password_hash=hash_password(temporary_password),
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="运营商邮箱或统一社会信用代码已存在") from error
    application.status = SupplierStatus.APPROVED.value
    application.review_notes = (payload.notes or "").strip() or None
    application.approved_organization_id = organization.id
    application.reviewed_by_user_id = admin.id
    application.reviewed_at = datetime.now(timezone.utc)
    record_event(
        db, event_type="OPERATOR_APPLICATION_APPROVED", entity_type="OperatorApplication",
        entity_id=application.id, organization_id=organization.id,
        actor_type="USER", actor_id=admin.id,
        payload={"application_no": application.application_no, "organization_code": code},
    )
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="运营商邮箱或统一社会信用代码已存在") from error
    return ApplicationApprovalResponse(
        application_id=application.id, application_no=application.application_no,
        status=application.status, organization_id=organization.id,
        organization_code=code, login_email=user.email,
        temporary_password=temporary_password,
        message="运营商组织与运营商账号已创建。临时密码只在本次响应中显示。",
    )


@router.post(
    "/operator-applications/{application_id}/reject",
    response_model=OperatorApplicationAdminView,
)
def reject_operator_application(
    application_id: str,
    payload: ApplicationReviewRequest,
    db: DbSession,
    admin: PlatformAdmin,
) -> OperatorApplicationAdminView:
    application = db.get(OperatorApplication, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="申请不存在")
    if application.status != SupplierStatus.PENDING.value:
        raise HTTPException(status_code=409, detail="只有待审核申请可以驳回")
    application.status = SupplierStatus.REJECTED.value
    application.review_notes = (payload.notes or "").strip() or "暂不符合当前接入条件"
    application.reviewed_by_user_id = admin.id
    application.reviewed_at = datetime.now(timezone.utc)
    record_event(
        db, event_type="OPERATOR_APPLICATION_REJECTED", entity_type="OperatorApplication",
        entity_id=application.id, organization_id=None, actor_type="USER", actor_id=admin.id,
        payload={"application_no": application.application_no},
    )
    db.commit()
    db.refresh(application)
    return operator_application_view(application)


@router.get("/applications", response_model=list[ApplicationAdminView])
def list_applications(
    db: DbSession,
    _: PlatformAdmin,
    application_status: str | None = Query(default=None, alias="status"),
    limit: int | None = Query(default=None, ge=1, le=1000),
) -> list[ApplicationAdminView]:
    stmt = select(SupplierApplication).order_by(
        SupplierApplication.created_at.desc(),
        SupplierApplication.id.desc(),
    )
    if application_status:
        stmt = stmt.where(SupplierApplication.status == application_status.upper())
    if limit is not None:
        stmt = stmt.limit(limit)
    return [application_view(item) for item in db.scalars(stmt).all()]


@router.post(
    "/applications/{application_id}/approve",
    response_model=ApplicationApprovalResponse,
)
def approve_application(
    application_id: str,
    payload: ApplicationReviewRequest,
    db: DbSession,
    admin: PlatformAdmin,
) -> ApplicationApprovalResponse:
    application = db.get(SupplierApplication, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="申请不存在")
    if application.status != SupplierStatus.PENDING.value:
        raise HTTPException(status_code=409, detail="只有待审核申请可以通过")

    existing_user = db.scalar(
        select(User).where(func.lower(User.email) == application.email.lower())
    )
    if existing_user is not None:
        raise HTTPException(status_code=409, detail="该邮箱已经关联现有账号")

    organization_code = generate_org_code(application)
    if db.scalar(select(Organization).where(Organization.code == organization_code)):
        organization_code = f"{organization_code}-{secrets.token_hex(2).upper()}"

    organization = Organization(
        code=organization_code,
        name=application.company_name,
        organization_type=OrganizationType.SUPPLIER.value,
    )
    db.add(organization)
    db.flush()

    profile = SupplierProfile(
        organization_id=organization.id,
        legal_name=application.company_name,
        unified_social_credit_code=application.unified_social_credit_code,
        supplier_type=normalize_supplier_type(application.company_type),
        province=application.province,
        city=application.city,
        contact_name=application.contact_name,
        contact_phone=application.phone,
        contact_email=application.email,
        categories=application.categories,
        cooperation_modes=application.cooperation_modes,
        supports_dropshipping=application.supports_dropshipping,
        supports_oem=application.supports_oem,
        has_export_experience=application.has_export_experience,
        status=SupplierStatus.APPROVED.value,
    )
    profile.profile_completion = calculate_profile_completion(profile)
    db.add(profile)

    temporary_password = generate_temporary_password()
    supplier_user = User(
        organization_id=organization.id,
        email=application.email.lower(),
        name=application.contact_name,
        role=UserRole.SUPPLIER.value,
        password_hash=hash_password(temporary_password),
    )
    db.add(supplier_user)
    db.flush()

    application.status = SupplierStatus.APPROVED.value
    application.review_notes = (payload.notes or "").strip() or None
    application.approved_organization_id = organization.id
    application.reviewed_by_user_id = admin.id
    application.reviewed_at = datetime.now(timezone.utc)

    record_event(
        db,
        event_type="SUPPLIER_APPLICATION_APPROVED",
        entity_type="SupplierApplication",
        entity_id=application.id,
        organization_id=organization.id,
        actor_type="USER",
        actor_id=admin.id,
        payload={
            "application_no": application.application_no,
            "organization_code": organization.code,
            "login_email": supplier_user.email,
        },
    )
    db.commit()
    return ApplicationApprovalResponse(
        application_id=application.id,
        application_no=application.application_no,
        status=application.status,
        organization_id=organization.id,
        organization_code=organization.code,
        login_email=supplier_user.email,
        temporary_password=temporary_password,
        message="供应商组织与供应商账号已创建。临时密码只在本次响应中显示。",
    )


@router.post("/applications/{application_id}/reject", response_model=ApplicationAdminView)
def reject_application(
    application_id: str,
    payload: ApplicationReviewRequest,
    db: DbSession,
    admin: PlatformAdmin,
) -> ApplicationAdminView:
    application = db.get(SupplierApplication, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="申请不存在")
    if application.status != SupplierStatus.PENDING.value:
        raise HTTPException(status_code=409, detail="只有待审核申请可以驳回")

    application.status = SupplierStatus.REJECTED.value
    application.review_notes = (payload.notes or "").strip() or "暂不符合当前接入条件"
    application.reviewed_by_user_id = admin.id
    application.reviewed_at = datetime.now(timezone.utc)
    record_event(
        db,
        event_type="SUPPLIER_APPLICATION_REJECTED",
        entity_type="SupplierApplication",
        entity_id=application.id,
        organization_id=None,
        actor_type="USER",
        actor_id=admin.id,
        payload={"application_no": application.application_no},
    )
    db.commit()
    db.refresh(application)
    return application_view(application)


@router.get("/suppliers", response_model=list[SupplierManagementView])
def list_suppliers(db: DbSession, _: PlatformAdmin) -> list[SupplierManagementView]:
    product_counts = (
        select(
            Product.created_by_organization_id.label("organization_id"),
            func.count(Product.id).label("product_count"),
        )
        .group_by(Product.created_by_organization_id)
        .subquery()
    )
    offer_counts = (
        select(
            SupplierOffer.organization_id.label("organization_id"),
            func.count(SupplierOffer.id).label("offer_count"),
        )
        .where(SupplierOffer.status == OfferStatus.ACTIVE.value)
        .group_by(SupplierOffer.organization_id)
        .subquery()
    )
    rows = db.execute(
        select(
            Organization,
            SupplierProfile,
            func.coalesce(product_counts.c.product_count, 0),
            func.coalesce(offer_counts.c.offer_count, 0),
        )
        .join(SupplierProfile, SupplierProfile.organization_id == Organization.id)
        .outerjoin(product_counts, product_counts.c.organization_id == Organization.id)
        .outerjoin(offer_counts, offer_counts.c.organization_id == Organization.id)
        .where(Organization.organization_type == OrganizationType.SUPPLIER.value)
        .order_by(Organization.created_at.desc())
    ).all()

    return [
        SupplierManagementView(
            organization_id=organization.id,
            organization_code=organization.code,
            organization_name=organization.name,
            legal_name=profile.legal_name,
            status=profile.status,
            profile_completion=profile.profile_completion,
            contact_name=profile.contact_name,
            contact_email=profile.contact_email,
            product_count=int(product_count),
            active_offer_count=int(offer_count),
            created_at=organization.created_at,
        )
        for organization, profile, product_count, offer_count in rows
    ]
