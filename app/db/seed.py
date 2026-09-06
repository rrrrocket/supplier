from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.security import hash_password
from app.models.entities import (
    OfferStatus,
    Organization,
    OrganizationType,
    Product,
    ProductStatus,
    SupplierApplication,
    SupplierOffer,
    SupplierProfile,
    SupplierStatus,
    User,
    UserRole,
)
from app.services.events import record_event
from app.services.scoring import calculate_profile_completion


def seed_database(db: Session, settings: Settings) -> None:
    """Create deterministic local demo records without duplicating existing data."""
    if not settings.seed_demo_data:
        return

    platform = db.scalar(select(Organization).where(Organization.code == "MATRIX-ONE"))
    if platform is None:
        platform = Organization(
            code="MATRIX-ONE",
            name="Matrix One",
            organization_type=OrganizationType.PLATFORM.value,
        )
        db.add(platform)
        db.flush()

    supplier = db.scalar(select(Organization).where(Organization.code == "DEMO-SUPPLIER"))
    if supplier is None:
        supplier = Organization(
            code="DEMO-SUPPLIER",
            name="示例供应商（演示数据）",
            organization_type=OrganizationType.SUPPLIER.value,
        )
        db.add(supplier)
        db.flush()

    admin_user = db.scalar(
        select(User).where(func.lower(User.email) == settings.demo_admin_email.lower())
    )
    if admin_user is None:
        admin_user = User(
            organization_id=platform.id,
            email=settings.demo_admin_email.lower(),
            name="平台管理员",
            role=UserRole.PLATFORM_ADMIN.value,
            password_hash=hash_password(settings.demo_admin_password),
        )
        db.add(admin_user)

    profile = db.scalar(
        select(SupplierProfile).where(SupplierProfile.organization_id == supplier.id)
    )
    profile_was_created = profile is None
    if profile is None:
        profile = SupplierProfile(
            organization_id=supplier.id,
            legal_name="深圳矩阵供应链示例有限公司",
            unified_social_credit_code="DEMO-91440300XXXXXXXXXX",
            supplier_type="FACTORY_TRADER",
            province="广东省",
            city="深圳市",
            address="演示地址，仅用于本地开发",
            contact_name="示例管理员",
            contact_phone="13800000000",
            contact_email=settings.demo_email.lower(),
            website="",
            categories=["工业自动化", "模型玩具", "汽摩用品"],
            cooperation_modes=["自营采购", "联营代运营", "B2B外贸"],
            export_markets=["俄罗斯", "中亚"],
            supports_dropshipping=True,
            supports_oem=True,
            has_export_experience=True,
            status=SupplierStatus.APPROVED.value,
        )
        profile.profile_completion = calculate_profile_completion(profile)
        db.add(profile)
        db.flush()

    demo_user = db.scalar(
        select(User).where(func.lower(User.email) == settings.demo_email.lower())
    )
    if demo_user is None:
        demo_user = User(
            organization_id=supplier.id,
            email=settings.demo_email.lower(),
            name="示例管理员",
            role=UserRole.SUPPLIER_ADMIN.value,
            password_hash=hash_password(settings.demo_password),
        )
        db.add(demo_user)

    existing_product_count = db.scalar(
        select(func.count(Product.id)).where(Product.created_by_organization_id == supplier.id)
    ) or 0
    if existing_product_count == 0:
        _seed_demo_products(db, supplier.id)

    demo_application = db.scalar(
        select(SupplierApplication).where(
            SupplierApplication.application_no == "SUP-DEMO-PENDING"
        )
    )
    if demo_application is None:
        db.add(
            SupplierApplication(
                application_no="SUP-DEMO-PENDING",
                company_name="宁波精工传感器示例厂",
                unified_social_credit_code="DEMO-PENDING-CODE",
                company_type="生产工厂",
                province="浙江省",
                city="宁波市",
                contact_name="王经理",
                phone="13900000000",
                email="pending-supplier@example.com",
                categories=["工业自动化"],
                cooperation_modes=["自营采购", "B2B外贸"],
                annual_revenue_range="500万–3000万元",
                supports_dropshipping=False,
                supports_oem=True,
                has_export_experience=True,
                message="演示申请：主营接近传感器、压力变送器和工业连接器。",
                status=SupplierStatus.PENDING.value,
            )
        )

    if profile_was_created:
        record_event(
            db,
            event_type="SUPPLIER_APPROVED",
            entity_type="SupplierProfile",
            entity_id=profile.id,
            organization_id=supplier.id,
            actor_type="SYSTEM",
            payload={"status": SupplierStatus.APPROVED.value},
        )

    db.commit()


def _seed_demo_products(db: Session, organization_id: str) -> None:
    demo_rows = [
        {
            "name": "M18 电感式接近传感器",
            "brand": "OEM",
            "model": "M18-PNP-NO-8MM",
            "category": "工业自动化/接近传感器",
            "attributes": {"尺寸": "M18", "输出": "PNP NO", "检测距离": "8mm"},
            "sku": "SENSOR-M18-001",
            "price": Decimal("46.50"),
            "moq": 10,
            "stock": 860,
            "lead": 3,
            "mode": "PURCHASE",
        },
        {
            "name": "47cm A350 航空模型（带轮带灯）",
            "brand": "OEM",
            "model": "A350-47-LED",
            "category": "模型玩具/航空模型",
            "attributes": {"机长": "约47cm", "配置": "带轮带灯"},
            "sku": "MODEL-A350-LED",
            "price": Decimal("218.00"),
            "moq": 2,
            "stock": 46,
            "lead": 2,
            "mode": "DROPSHIP",
        },
        {
            "name": "全盔 亚洲头型 哑光黑",
            "brand": "OEM",
            "model": "FF-ASIA-MB",
            "category": "汽摩用品/摩托车头盔",
            "attributes": {"颜色": "哑光黑", "版型": "亚洲头型"},
            "sku": "HELMET-FF-MB",
            "price": Decimal("286.00"),
            "moq": 5,
            "stock": 9,
            "lead": 5,
            "mode": "PURCHASE",
        },
        {
            "name": "户外便携式 12V 水泵",
            "brand": "OEM",
            "model": "WP-12V-60W",
            "category": "户外用品/水泵",
            "attributes": {"电压": "12V", "功率": "60W"},
            "sku": "OUTDOOR-PUMP-12V",
            "price": Decimal("79.90"),
            "moq": 20,
            "stock": 0,
            "lead": 7,
            "mode": "PURCHASE",
        },
    ]

    for row in demo_rows:
        product = Product(
            created_by_organization_id=organization_id,
            name=row["name"],
            brand=row["brand"],
            model=row["model"],
            category=row["category"],
            attributes=row["attributes"],
            status=ProductStatus.ACTIVE.value,
        )
        db.add(product)
        db.flush()

        offer = SupplierOffer(
            organization_id=organization_id,
            product_id=product.id,
            supplier_sku=row["sku"],
            price=row["price"],
            currency="CNY",
            moq=row["moq"],
            stock_qty=row["stock"],
            lead_time_days=row["lead"],
            fulfillment_mode=row["mode"],
            status=OfferStatus.ACTIVE.value,
        )
        db.add(offer)
        db.flush()

        record_event(
            db,
            event_type="OFFER_CREATED",
            entity_type="SupplierOffer",
            entity_id=offer.id,
            organization_id=organization_id,
            actor_type="SYSTEM",
            payload={"supplier_sku": offer.supplier_sku, "product_name": product.name},
        )
