from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import func, select

from app.api.deps import DbSession
from app.models.entities import (
    OfferStatus,
    OperatorProfile,
    Organization,
    OrganizationType,
    Product,
    SupplierOffer,
    SupplierProfile,
    SupplierStatus,
    User,
    UserRole,
)
from app.schemas.directory import (
    OperatorDirectoryItem,
    OperatorDirectoryPage,
    SupplierDirectoryItem,
    SupplierDirectoryPage,
)
from app.services.events import record_event


router = APIRouter(prefix="/public/suppliers", tags=["供应商市场"])
operator_router = APIRouter(prefix="/public/operators", tags=["运营商市场"])


def mask_phone(value: str | None) -> str | None:
    if not value:
        return None
    return f"{value[:3]}****{value[-4:]}" if len(value) >= 7 else "****"


def mask_email(value: str | None) -> str | None:
    if not value or "@" not in value:
        return None
    name, domain = value.split("@", 1)
    return f"{name[:1]}***@{domain}"


def current_user(request: Request, db: DbSession) -> User | None:
    user_id = request.session.get("user_id")
    return db.get(User, user_id) if user_id else None


def is_active_supplier(user: User | None) -> bool:
    return bool(
        user
        and user.is_active
        and user.organization.is_active
        and user.role == UserRole.SUPPLIER.value
        and user.organization.organization_type == OrganizationType.SUPPLIER.value
    )


def eligible_rows(db: DbSession) -> list[tuple[Organization, SupplierProfile]]:
    return list(db.execute(
        select(Organization, SupplierProfile).join(
            SupplierProfile, SupplierProfile.organization_id == Organization.id
        ).where(
            Organization.organization_type == OrganizationType.SUPPLIER.value,
            Organization.is_active.is_(True),
            SupplierProfile.status == SupplierStatus.APPROVED.value,
        ).order_by(Organization.created_at.desc(), Organization.id.desc())
    ).all())


def serialize(db: DbSession, org: Organization, profile: SupplierProfile, full: bool) -> SupplierDirectoryItem:
    products = db.scalar(select(func.count(Product.id)).where(Product.created_by_organization_id == org.id)) or 0
    offers = db.scalar(select(func.count(SupplierOffer.id)).where(
        SupplierOffer.organization_id == org.id, SupplierOffer.status == OfferStatus.ACTIVE.value
    )) or 0
    return SupplierDirectoryItem(
        supplier_id=org.id, supplier_code=org.code, supplier_name=org.name,
        legal_name=profile.legal_name, supplier_type=profile.supplier_type,
        province=profile.province, city=profile.city, website=profile.website,
        categories=profile.categories, cooperation_modes=profile.cooperation_modes,
        supports_dropshipping=profile.supports_dropshipping, supports_oem=profile.supports_oem,
        has_export_experience=profile.has_export_experience,
        product_count=products, active_offer_count=offers,
        contact_name=profile.contact_name if full else (profile.contact_name[:1] + "**" if profile.contact_name else None),
        contact_phone=profile.contact_phone if full else mask_phone(profile.contact_phone),
        contact_email=profile.contact_email if full else mask_email(profile.contact_email),
    )


@router.get("", response_model=SupplierDirectoryPage)
def list_suppliers(
    db: DbSession, page: int = Query(1, ge=1), page_size: int = Query(50),
    keyword: str | None = None, category: str | None = None, region: str | None = None,
    supplier_type: str | None = None, cooperation_mode: str | None = None,
    supports_dropshipping: bool | None = None, supports_oem: bool | None = None,
    has_export_experience: bool | None = None,
) -> SupplierDirectoryPage:
    if page_size not in {50, 100, 200}:
        raise HTTPException(status_code=422, detail="页面行数仅支持 50、100 或 200")
    rows = eligible_rows(db)
    key = (keyword or "").strip().lower()
    def matches(row: tuple[Organization, SupplierProfile]) -> bool:
        org, profile = row
        haystack = " ".join([org.name, profile.legal_name, profile.province or "", profile.city or "", *profile.categories]).lower()
        return (
            (not key or key in haystack)
            and (not category or category in profile.categories)
            and (not region or region in {profile.province, profile.city})
            and (not supplier_type or profile.supplier_type == supplier_type)
            and (not cooperation_mode or cooperation_mode in profile.cooperation_modes)
            and (supports_dropshipping is None or profile.supports_dropshipping == supports_dropshipping)
            and (supports_oem is None or profile.supports_oem == supports_oem)
            and (has_export_experience is None or profile.has_export_experience == has_export_experience)
        )
    filtered = [row for row in rows if matches(row)]
    start = (page - 1) * page_size
    return SupplierDirectoryPage(
        items=[serialize(db, org, profile, False) for org, profile in filtered[start:start + page_size]],
        total=len(filtered), page=page, page_size=page_size,
    )


@router.get("/{supplier_id}", response_model=SupplierDirectoryItem)
def supplier_detail(supplier_id: str, request: Request, db: DbSession) -> SupplierDirectoryItem:
    pair = next((row for row in eligible_rows(db) if row[0].id == supplier_id), None)
    if pair is None:
        raise HTTPException(status_code=404, detail="供应商不存在")
    user = db.get(User, request.session.get("user_id")) if request.session.get("user_id") else None
    full = bool(user and user.is_active and user.organization.is_active and user.role == UserRole.OPERATOR.value
                and user.organization.organization_type == OrganizationType.OPERATOR.value)
    if full and user:
        record_event(
            db, event_type="SUPPLIER_CONTACT_VIEWED", entity_type="Organization",
            entity_id=supplier_id, organization_id=user.organization_id,
            actor_type="USER", actor_id=user.id,
        )
        db.commit()
    return serialize(db, pair[0], pair[1], full)


def eligible_operator_rows(db: DbSession) -> list[tuple[Organization, OperatorProfile]]:
    return list(db.execute(
        select(Organization, OperatorProfile).join(
            OperatorProfile, OperatorProfile.organization_id == Organization.id
        ).where(
            Organization.organization_type == OrganizationType.OPERATOR.value,
            Organization.is_active.is_(True),
        ).order_by(Organization.created_at.desc(), Organization.id.desc())
    ).all())


def serialize_operator(
    org: Organization, profile: OperatorProfile, full: bool
) -> OperatorDirectoryItem:
    public_name = profile.company_name or f"{profile.contact_name[:1]}**的运营团队"
    return OperatorDirectoryItem(
        operator_id=org.id,
        operator_code=org.code,
        operator_name=org.name if full else public_name,
        company_name=profile.company_name,
        operator_type=profile.operator_type,
        province=profile.province,
        city=profile.city,
        website=profile.website,
        erp_name=profile.erp_name,
        sales_channels=profile.sales_channels,
        categories=profile.categories,
        target_markets=profile.target_markets,
        contact_name=(profile.contact_name if full else profile.contact_name[:1] + "**"),
        contact_phone=(profile.contact_phone if full else mask_phone(profile.contact_phone)),
        contact_email=(profile.contact_email if full else mask_email(profile.contact_email)),
    )


@operator_router.get("", response_model=OperatorDirectoryPage)
def list_operators(
    db: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(50),
    keyword: str | None = None,
    category: str | None = None,
    region: str | None = None,
    operator_type: str | None = None,
    erp_name: str | None = None,
) -> OperatorDirectoryPage:
    if page_size not in {50, 100, 200}:
        raise HTTPException(status_code=422, detail="页面行数仅支持 50、100 或 200")
    key = (keyword or "").strip().lower()

    def matches(row: tuple[Organization, OperatorProfile]) -> bool:
        org, profile = row
        haystack = " ".join([
            profile.company_name or "",
            profile.operator_type or "",
            profile.province or "",
            profile.city or "",
            profile.erp_name or "",
            *profile.categories,
            *profile.sales_channels,
            *profile.target_markets,
        ]).lower()
        return (
            (not key or key in haystack)
            and (not category or category in profile.categories)
            and (not region or region in {profile.province, profile.city})
            and (not operator_type or profile.operator_type == operator_type)
            and (not erp_name or profile.erp_name == erp_name)
        )

    filtered = [row for row in eligible_operator_rows(db) if matches(row)]
    start = (page - 1) * page_size
    return OperatorDirectoryPage(
        items=[serialize_operator(org, profile, False) for org, profile in filtered[start:start + page_size]],
        total=len(filtered),
        page=page,
        page_size=page_size,
    )


@operator_router.get("/{operator_id}", response_model=OperatorDirectoryItem)
def operator_detail(operator_id: str, request: Request, db: DbSession) -> OperatorDirectoryItem:
    pair = next((row for row in eligible_operator_rows(db) if row[0].id == operator_id), None)
    if pair is None:
        raise HTTPException(status_code=404, detail="运营商不存在")
    user = current_user(request, db)
    full = is_active_supplier(user)
    if full and user:
        record_event(
            db,
            event_type="OPERATOR_CONTACT_VIEWED",
            entity_type="Organization",
            entity_id=operator_id,
            organization_id=user.organization_id,
            actor_type="USER",
            actor_id=user.id,
        )
        db.commit()
    return serialize_operator(pair[0], pair[1], full)
