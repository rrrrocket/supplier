"""add supplier catalog entities

Revision ID: 9a61d5c312ef
Revises: 7f22c89a41bd
Create Date: 2026-09-08 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "9a61d5c312ef"
down_revision: Union[str, Sequence[str], None] = "7f22c89a41bd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()
    invalid_product_count = connection.execute(
        sa.text(
            """
            SELECT count(DISTINCT products.id)
            FROM products
            JOIN supplier_offers ON supplier_offers.product_id = products.id
            WHERE btrim(coalesce(products.brand, '')) = ''
            """
        )
    ).scalar_one()
    if invalid_product_count:
        raise RuntimeError(
            f"{invalid_product_count} offered product(s) have an empty brand"
        )

    op.create_table(
        "brands",
        sa.Column("code", sa.String(length=60), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("normalized_name", sa.String(length=160), nullable=False),
        sa.Column("aliases", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_brands_code", "brands", ["code"], unique=True)
    op.create_index(
        "ix_brands_normalized_name", "brands", ["normalized_name"], unique=False
    )
    op.create_index("ix_brands_status", "brands", ["status"], unique=False)

    op.create_table(
        "supplier_brand_cooperations",
        sa.Column("supplier_id", sa.String(length=36), nullable=False),
        sa.Column("brand_id", sa.String(length=36), nullable=False),
        sa.Column("commercial_mode", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["supplier_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["brand_id"], ["brands.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_supplier_brand_cooperations_supplier_id",
        "supplier_brand_cooperations",
        ["supplier_id"],
        unique=False,
    )
    op.create_index(
        "ix_supplier_brand_cooperations_brand_id",
        "supplier_brand_cooperations",
        ["brand_id"],
        unique=False,
    )
    op.create_index(
        "ix_supplier_brand_cooperations_status",
        "supplier_brand_cooperations",
        ["status"],
        unique=False,
    )
    op.create_index(
        "uq_active_supplier_brand_cooperation",
        "supplier_brand_cooperations",
        ["supplier_id", "brand_id"],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )

    op.add_column(
        "products", sa.Column("brand_id", sa.String(length=36), nullable=True)
    )
    op.create_foreign_key(
        "fk_products_brand_id_brands",
        "products",
        "brands",
        ["brand_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_products_brand_id", "products", ["brand_id"], unique=False)

    op.create_table(
        "supplier_skus",
        sa.Column("supplier_id", sa.String(length=36), nullable=False),
        sa.Column("brand_id", sa.String(length=36), nullable=False),
        sa.Column("product_id", sa.String(length=36), nullable=False),
        sa.Column("variant_id", sa.String(length=36), nullable=True),
        sa.Column("supplier_sku_code", sa.String(length=120), nullable=False),
        sa.Column("manufacturer_part_number", sa.String(length=160), nullable=True),
        sa.Column("barcode", sa.String(length=80), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["supplier_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["brand_id"], ["brands.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["variant_id"], ["product_variants.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "supplier_id", "supplier_sku_code", name="uq_supplier_sku_code"
        ),
    )
    for column_name in (
        "supplier_id",
        "brand_id",
        "product_id",
        "variant_id",
        "supplier_sku_code",
        "manufacturer_part_number",
        "barcode",
        "status",
    ):
        op.create_index(
            f"ix_supplier_skus_{column_name}",
            "supplier_skus",
            [column_name],
            unique=False,
        )

    op.add_column(
        "supplier_offers",
        sa.Column("supplier_sku_id", sa.String(length=36), nullable=True),
    )
    op.create_foreign_key(
        "fk_supplier_offers_supplier_sku_id_supplier_skus",
        "supplier_offers",
        "supplier_skus",
        ["supplier_sku_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_supplier_offers_supplier_sku_id",
        "supplier_offers",
        ["supplier_sku_id"],
        unique=True,
    )

    op.execute(
        sa.text(
            r"""
            WITH normalized_products AS (
                SELECT
                    btrim(brand) AS name,
                    lower(regexp_replace(btrim(brand), '\s+', ' ', 'g')) AS normalized_name
                FROM products
                WHERE btrim(coalesce(brand, '')) <> ''
            ), representatives AS (
                SELECT DISTINCT ON (normalized_name) name, normalized_name
                FROM normalized_products
                ORDER BY normalized_name, name
            )
            INSERT INTO brands
                (id, code, name, normalized_name, aliases, status, created_at, updated_at)
            SELECT
                gen_random_uuid()::text,
                'BR-' || upper(substr(md5(normalized_name), 1, 10)),
                name,
                normalized_name,
                '[]'::json,
                'ACTIVE',
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            FROM representatives
            """
        )
    )
    op.execute(
        sa.text(
            r"""
            UPDATE products
            SET brand_id = brands.id
            FROM brands
            WHERE lower(regexp_replace(btrim(products.brand), '\s+', ' ', 'g')) =
                  brands.normalized_name
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO supplier_brand_cooperations
                (id, supplier_id, brand_id, commercial_mode, status,
                 valid_from, valid_to, notes, created_at, updated_at)
            SELECT DISTINCT
                gen_random_uuid()::text,
                offers.organization_id,
                products.brand_id,
                'SELF_PURCHASE',
                'ACTIVE',
                NULL::date,
                NULL::date,
                NULL::text,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            FROM supplier_offers AS offers
            JOIN products ON products.id = offers.product_id
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO supplier_skus
                (id, supplier_id, brand_id, product_id, variant_id,
                 supplier_sku_code, manufacturer_part_number, barcode,
                 status, created_at, updated_at)
            SELECT
                offers.id,
                offers.organization_id,
                products.brand_id,
                offers.product_id,
                offers.variant_id,
                offers.supplier_sku,
                NULL,
                NULL,
                'ACTIVE',
                offers.created_at,
                offers.updated_at
            FROM supplier_offers AS offers
            JOIN products ON products.id = offers.product_id
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE supplier_offers
            SET supplier_sku_id = id
            """
        )
    )


def downgrade() -> None:
    op.drop_index(
        "ix_supplier_offers_supplier_sku_id", table_name="supplier_offers"
    )
    op.drop_constraint(
        "fk_supplier_offers_supplier_sku_id_supplier_skus",
        "supplier_offers",
        type_="foreignkey",
    )
    op.drop_column("supplier_offers", "supplier_sku_id")

    op.drop_table("supplier_skus")

    op.drop_index("ix_products_brand_id", table_name="products")
    op.drop_constraint(
        "fk_products_brand_id_brands", "products", type_="foreignkey"
    )
    op.drop_column("products", "brand_id")

    op.drop_table("supplier_brand_cooperations")
    op.drop_table("brands")
