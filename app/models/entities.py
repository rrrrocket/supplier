from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, utcnow


class OrganizationType(str, Enum):
    PLATFORM = "PLATFORM"
    SUPPLIER = "SUPPLIER"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PLATFORM_ADMIN"
    SUPPLIER = "SUPPLIER"


class SupplierStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"


class ProductStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class OfferStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    EXPIRED = "EXPIRED"


class ImportStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class Organization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "organizations"

    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    organization_type: Mapped[str] = mapped_column(
        String(30), default=OrganizationType.SUPPLIER.value, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    users: Mapped[list[User]] = relationship(back_populates="organization")
    supplier_profile: Mapped[SupplierProfile | None] = relationship(
        back_populates="organization", uselist=False
    )
    products: Mapped[list[Product]] = relationship(back_populates="created_by_organization")
    offers: Mapped[list[SupplierOffer]] = relationship(back_populates="organization")


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[str] = mapped_column(
        String(40), default=UserRole.SUPPLIER.value, nullable=False
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    organization: Mapped[Organization] = relationship(back_populates="users")


class SupplierProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "supplier_profiles"

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    legal_name: Mapped[str] = mapped_column(String(240), nullable=False)
    unified_social_credit_code: Mapped[str | None] = mapped_column(String(40), index=True)
    supplier_type: Mapped[str] = mapped_column(String(40), default="FACTORY", nullable=False)
    province: Mapped[str | None] = mapped_column(String(80))
    city: Mapped[str | None] = mapped_column(String(80))
    address: Mapped[str | None] = mapped_column(String(300))
    contact_name: Mapped[str | None] = mapped_column(String(100))
    contact_phone: Mapped[str | None] = mapped_column(String(60))
    contact_email: Mapped[str | None] = mapped_column(String(255))
    website: Mapped[str | None] = mapped_column(String(255))
    categories: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    cooperation_modes: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    export_markets: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    supports_dropshipping: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    supports_oem: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    has_export_experience: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), default=SupplierStatus.DRAFT.value, nullable=False, index=True
    )
    profile_completion: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    internal_notes: Mapped[str | None] = mapped_column(Text)

    organization: Mapped[Organization] = relationship(back_populates="supplier_profile")


class SupplierApplication(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "supplier_applications"

    application_no: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    company_name: Mapped[str] = mapped_column(String(240), nullable=False)
    unified_social_credit_code: Mapped[str | None] = mapped_column(String(40), index=True)
    company_type: Mapped[str] = mapped_column(String(40), nullable=False)
    province: Mapped[str] = mapped_column(String(80), nullable=False)
    city: Mapped[str] = mapped_column(String(80), nullable=False)
    contact_name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str] = mapped_column(String(60), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    categories: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    cooperation_modes: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    annual_revenue_range: Mapped[str | None] = mapped_column(String(60))
    supports_dropshipping: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    supports_oem: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    has_export_experience: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    message: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(30), default=SupplierStatus.PENDING.value, nullable=False, index=True
    )
    review_notes: Mapped[str | None] = mapped_column(Text)
    approved_organization_id: Mapped[str | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"), index=True
    )
    reviewed_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Product(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint(
            "created_by_organization_id",
            "brand",
            "model",
            "name",
            name="uq_product_supplier_brand_model_name",
        ),
    )

    created_by_organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(240), nullable=False, index=True)
    brand: Mapped[str | None] = mapped_column(String(120), index=True)
    model: Mapped[str | None] = mapped_column(String(120), index=True)
    category: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), default=ProductStatus.DRAFT.value, nullable=False, index=True
    )

    created_by_organization: Mapped[Organization] = relationship(back_populates="products")
    variants: Mapped[list[ProductVariant]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )
    offers: Mapped[list[SupplierOffer]] = relationship(back_populates="product")


class ProductVariant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "product_variants"

    product_id: Mapped[str] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    product: Mapped[Product] = relationship(back_populates="variants")
    offers: Mapped[list[SupplierOffer]] = relationship(back_populates="variant")


class SupplierOffer(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "supplier_offers"
    __table_args__ = (
        UniqueConstraint("organization_id", "supplier_sku", name="uq_supplier_offer_sku"),
    )

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[str] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    variant_id: Mapped[str | None] = mapped_column(
        ForeignKey("product_variants.id", ondelete="SET NULL"), index=True
    )
    supplier_sku: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    price: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="CNY", nullable=False)
    moq: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    stock_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    lead_time_days: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    fulfillment_mode: Mapped[str] = mapped_column(
        String(40), default="PURCHASE", nullable=False
    )
    valid_until: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(
        String(30), default=OfferStatus.DRAFT.value, nullable=False, index=True
    )
    notes: Mapped[str | None] = mapped_column(Text)

    organization: Mapped[Organization] = relationship(back_populates="offers")
    product: Mapped[Product] = relationship(back_populates="offers")
    variant: Mapped[ProductVariant | None] = relationship(back_populates="offers")
    inventory_snapshots: Mapped[list[InventorySnapshot]] = relationship(
        back_populates="offer", cascade="all, delete-orphan"
    )


class InventorySnapshot(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "inventory_snapshots"

    offer_id: Mapped[str] = mapped_column(
        ForeignKey("supplier_offers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
    source: Mapped[str] = mapped_column(String(40), default="MANUAL", nullable=False)

    offer: Mapped[SupplierOffer] = relationship(back_populates="inventory_snapshots")


class ImportJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "import_jobs"

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    import_type: Mapped[str] = mapped_column(String(40), default="PRODUCT_OFFER", nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), default=ImportStatus.PENDING.value, nullable=False, index=True
    )
    total_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    success_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    errors: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)


class Document(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "documents"

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    object_key: Mapped[str] = mapped_column(String(500), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(120))
    file_hash: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(30), default="PENDING", nullable=False)
    expires_at: Mapped[date | None] = mapped_column(Date)


class EventLog(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "event_logs"

    organization_id: Mapped[str | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"), index=True
    )
    actor_type: Mapped[str] = mapped_column(String(30), default="SYSTEM", nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(36), index=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    entity_id: Mapped[str | None] = mapped_column(String(36), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
