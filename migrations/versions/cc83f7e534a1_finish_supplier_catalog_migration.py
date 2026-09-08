"""finish supplier catalog migration

Revision ID: cc83f7e534a1
Revises: b742e6d423f0
Create Date: 2026-09-09 18:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "cc83f7e534a1"
down_revision: Union[str, Sequence[str], None] = "b742e6d423f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()
    missing_product_brand_count = connection.execute(
        sa.text("SELECT count(*) FROM products WHERE brand_id IS NULL")
    ).scalar_one()
    missing_offer_sku_count = connection.execute(
        sa.text("SELECT count(*) FROM supplier_offers WHERE supplier_sku_id IS NULL")
    ).scalar_one()
    if missing_product_brand_count or missing_offer_sku_count:
        raise RuntimeError(
            f"{missing_product_brand_count} product(s) lack brand_id; "
            f"{missing_offer_sku_count} supplier offer(s) lack supplier_sku_id"
        )

    op.drop_constraint(
        "uq_product_supplier_brand_model_name",
        "products",
        type_="unique",
    )
    op.drop_constraint(
        "fk_products_brand_id_brands",
        "products",
        type_="foreignkey",
    )
    op.alter_column(
        "products",
        "brand_id",
        existing_type=sa.String(length=36),
        nullable=False,
    )
    op.create_foreign_key(
        "fk_products_brand_id_brands",
        "products",
        "brands",
        ["brand_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_product_supplier_brand_model_name",
        "products",
        ["created_by_organization_id", "brand_id", "model", "name"],
    )
    op.drop_index("ix_products_brand", table_name="products")
    op.drop_column("products", "brand")

    op.drop_constraint(
        "uq_supplier_offer_sku",
        "supplier_offers",
        type_="unique",
    )
    op.drop_index(
        "ix_supplier_offers_supplier_sku_id",
        table_name="supplier_offers",
    )
    op.alter_column(
        "supplier_offers",
        "supplier_sku_id",
        existing_type=sa.String(length=36),
        nullable=False,
    )
    op.create_unique_constraint(
        "uq_supplier_offer_supplier_sku_id",
        "supplier_offers",
        ["supplier_sku_id"],
    )
    op.drop_index("ix_supplier_offers_supplier_sku", table_name="supplier_offers")
    op.drop_column("supplier_offers", "supplier_sku")


def downgrade() -> None:
    op.add_column(
        "products",
        sa.Column("brand", sa.String(length=160), nullable=True),
    )
    op.execute(
        sa.text(
            """
            UPDATE products
            SET brand = brands.name
            FROM brands
            WHERE brands.id = products.brand_id
            """
        )
    )
    op.create_index("ix_products_brand", "products", ["brand"], unique=False)

    op.add_column(
        "supplier_offers",
        sa.Column("supplier_sku", sa.String(length=120), nullable=True),
    )
    op.execute(
        sa.text(
            """
            UPDATE supplier_offers
            SET supplier_sku = supplier_skus.supplier_sku_code
            FROM supplier_skus
            WHERE supplier_skus.id = supplier_offers.supplier_sku_id
            """
        )
    )
    op.alter_column(
        "supplier_offers",
        "supplier_sku",
        existing_type=sa.String(length=120),
        nullable=False,
    )
    op.create_index(
        "ix_supplier_offers_supplier_sku",
        "supplier_offers",
        ["supplier_sku"],
        unique=False,
    )

    op.drop_constraint(
        "uq_product_supplier_brand_model_name",
        "products",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_product_supplier_brand_model_name",
        "products",
        ["created_by_organization_id", "brand", "model", "name"],
    )
    op.drop_constraint(
        "fk_products_brand_id_brands",
        "products",
        type_="foreignkey",
    )
    op.alter_column(
        "products",
        "brand_id",
        existing_type=sa.String(length=36),
        nullable=True,
    )
    op.create_foreign_key(
        "fk_products_brand_id_brands",
        "products",
        "brands",
        ["brand_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.drop_constraint(
        "uq_supplier_offer_supplier_sku_id",
        "supplier_offers",
        type_="unique",
    )
    op.create_index(
        "ix_supplier_offers_supplier_sku_id",
        "supplier_offers",
        ["supplier_sku_id"],
        unique=True,
    )
    op.create_unique_constraint(
        "uq_supplier_offer_sku",
        "supplier_offers",
        ["organization_id", "supplier_sku"],
    )
    op.alter_column(
        "supplier_offers",
        "supplier_sku_id",
        existing_type=sa.String(length=36),
        nullable=True,
    )
