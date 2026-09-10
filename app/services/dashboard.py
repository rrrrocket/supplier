from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.entities import EventLog, OfferStatus, Product, SupplierOffer, SupplierProfile
from app.schemas.dashboard import ChecklistItem, DashboardResponse, EventView, MetricCard
from app.services.scoring import calculate_profile_completion


def build_dashboard(db: Session, organization_id: str, organization_name: str) -> DashboardResponse:
    profile = db.scalar(
        select(SupplierProfile).where(SupplierProfile.organization_id == organization_id)
    )

    total_products = db.scalar(
        select(func.count(Product.id)).where(
            Product.created_by_organization_id == organization_id
        )
    ) or 0
    active_offers = db.scalar(
        select(func.count(SupplierOffer.id)).where(
            SupplierOffer.organization_id == organization_id,
            SupplierOffer.status == OfferStatus.ACTIVE.value,
        )
    ) or 0
    low_stock_offers = db.scalar(
        select(func.count(SupplierOffer.id)).where(
            SupplierOffer.organization_id == organization_id,
            SupplierOffer.status == OfferStatus.ACTIVE.value,
            SupplierOffer.stock_qty <= 10,
        )
    ) or 0
    stale_offers = db.scalar(
        select(func.count(SupplierOffer.id)).where(
            SupplierOffer.organization_id == organization_id,
            SupplierOffer.status != OfferStatus.ACTIVE.value,
        )
    ) or 0

    profile_completion = calculate_profile_completion(profile)
    if profile and profile.profile_completion != profile_completion:
        profile.profile_completion = profile_completion
        db.flush()

    recent = db.scalars(
        select(EventLog)
        .where(EventLog.organization_id == organization_id)
        .order_by(EventLog.occurred_at.desc())
        .limit(8)
    ).all()

    checklist = [
        ChecklistItem(
            key="company_profile",
            label="完善企业资料",
            description="补全主体、联系人、经营类目与合作能力。",
            completed=profile_completion >= 80,
            action_hash="#settings",
        ),
        ChecklistItem(
            key="products",
            label="建立商品报价",
            description="至少录入 10 个可实际供货的商品。",
            completed=total_products >= 10,
            action_hash="#offers",
        ),
        ChecklistItem(
            key="offers",
            label="激活商品报价",
            description="为商品维护成本、MOQ、库存和交期。",
            completed=active_offers >= 10,
            action_hash="#offers",
        ),
        ChecklistItem(
            key="inventory",
            label="完成首次库存更新",
            description="确保平台能够获得可执行的库存数据。",
            completed=active_offers > 0 and low_stock_offers < active_offers,
            action_hash="#imports",
        ),
        ChecklistItem(
            key="documents",
            label="提交资质文件",
            description="营业执照、产品认证和可选的工厂资料。",
            completed=False,
            action_hash="#documents",
        ),
    ]

    metrics = [
        MetricCard(
            key="products",
            label="商品数量",
            value=total_products,
            hint="已进入供应网络",
            tone="blue",
        ),
        MetricCard(
            key="active_offers",
            label="有效报价",
            value=active_offers,
            hint="可参与渠道匹配",
            tone="green",
        ),
        MetricCard(
            key="low_stock",
            label="低库存提醒",
            value=low_stock_offers,
            hint="库存 ≤ 10",
            tone="orange" if low_stock_offers else "neutral",
        ),
        MetricCard(
            key="pending",
            label="待处理数据",
            value=stale_offers,
            hint="草稿、暂停或过期报价",
            tone="purple",
        ),
    ]

    return DashboardResponse(
        organization_name=organization_name,
        supplier_status=profile.status if profile else "DRAFT",
        profile_completion=profile_completion,
        metrics=metrics,
        checklist=checklist,
        recent_events=[
            EventView(
                id=event.id,
                event_type=event.event_type,
                entity_type=event.entity_type,
                entity_id=event.entity_id,
                payload=event.payload,
                occurred_at=event.occurred_at,
            )
            for event in recent
        ],
    )
