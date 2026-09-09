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

    invalid_domain_count = connection.execute(
        sa.text(
            """
            SELECT count(*)
            FROM supplier_skus AS sku
            JOIN products AS product ON product.id = sku.product_id
            JOIN organizations AS supplier ON supplier.id = sku.supplier_id
            LEFT JOIN product_variants AS variant ON variant.id = sku.variant_id
            WHERE supplier.organization_type <> 'SUPPLIER'
               OR product.created_by_organization_id <> sku.supplier_id
               OR product.brand_id <> sku.brand_id
               OR (sku.variant_id IS NOT NULL AND variant.product_id <> sku.product_id)
            """
        )
    ).scalar_one()
    invalid_offer_domain_count = connection.execute(
        sa.text(
            """
            SELECT count(*)
            FROM supplier_offers AS offer
            JOIN supplier_skus AS sku ON sku.id = offer.supplier_sku_id
            LEFT JOIN product_variants AS variant ON variant.id = offer.variant_id
            WHERE offer.organization_id <> sku.supplier_id
               OR offer.product_id <> sku.product_id
               OR offer.variant_id IS DISTINCT FROM sku.variant_id
               OR (offer.variant_id IS NOT NULL AND variant.product_id <> offer.product_id)
            """
        )
    ).scalar_one()
    if invalid_domain_count or invalid_offer_domain_count:
        raise RuntimeError(
            f"{invalid_domain_count} supplier SKU domain mismatch row(s); "
            f"{invalid_offer_domain_count} supplier offer domain mismatch row(s)"
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

    op.execute(
        sa.text(
            """
            CREATE FUNCTION enforce_supplier_sku_domain() RETURNS trigger AS $$
            BEGIN
                PERFORM 1
                FROM products AS product
                JOIN organizations AS supplier
                  ON supplier.id = NEW.supplier_id
                 AND supplier.organization_type = 'SUPPLIER'
                WHERE product.id = NEW.product_id
                  AND product.created_by_organization_id = NEW.supplier_id
                  AND product.brand_id = NEW.brand_id
                FOR KEY SHARE OF product, supplier;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'supplier SKU domain mismatch';
                END IF;
                IF NEW.variant_id IS NOT NULL THEN
                    PERFORM 1
                    FROM product_variants AS variant
                    WHERE variant.id = NEW.variant_id
                      AND variant.product_id = NEW.product_id
                    FOR KEY SHARE OF variant;
                    IF NOT FOUND THEN
                        RAISE EXCEPTION 'supplier SKU domain mismatch';
                    END IF;
                END IF;
                IF EXISTS (
                    SELECT 1
                    FROM supplier_offers AS offer
                    WHERE offer.supplier_sku_id = NEW.id
                      AND (
                          offer.organization_id <> NEW.supplier_id
                          OR offer.product_id <> NEW.product_id
                          OR offer.variant_id IS DISTINCT FROM NEW.variant_id
                      )
                ) THEN
                    RAISE EXCEPTION 'supplier offer domain mismatch';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;

            CREATE TRIGGER trg_supplier_sku_domain
            BEFORE INSERT OR UPDATE OF supplier_id, brand_id, product_id, variant_id
            ON supplier_skus FOR EACH ROW EXECUTE FUNCTION enforce_supplier_sku_domain();

            CREATE FUNCTION enforce_supplier_offer_domain() RETURNS trigger AS $$
            BEGIN
                PERFORM 1
                FROM supplier_skus AS sku
                WHERE sku.id = NEW.supplier_sku_id
                  AND sku.supplier_id = NEW.organization_id
                  AND sku.product_id = NEW.product_id
                  AND sku.variant_id IS NOT DISTINCT FROM NEW.variant_id
                FOR KEY SHARE OF sku;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'supplier offer domain mismatch';
                END IF;
                IF NEW.variant_id IS NOT NULL THEN
                    PERFORM 1
                    FROM product_variants AS variant
                    WHERE variant.id = NEW.variant_id
                      AND variant.product_id = NEW.product_id
                    FOR KEY SHARE OF variant;
                    IF NOT FOUND THEN
                        RAISE EXCEPTION 'supplier offer domain mismatch';
                    END IF;
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;

            CREATE TRIGGER trg_supplier_offer_domain
            BEFORE INSERT OR UPDATE OF organization_id, product_id, variant_id, supplier_sku_id
            ON supplier_offers FOR EACH ROW EXECUTE FUNCTION enforce_supplier_offer_domain();

            CREATE FUNCTION enforce_product_catalog_domain() RETURNS trigger AS $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM supplier_skus AS sku
                    WHERE sku.product_id = NEW.id
                      AND (
                          sku.supplier_id <> NEW.created_by_organization_id
                          OR sku.brand_id <> NEW.brand_id
                      )
                ) THEN
                    RAISE EXCEPTION 'product catalog domain mismatch';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;

            CREATE TRIGGER trg_product_catalog_domain
            BEFORE UPDATE OF created_by_organization_id, brand_id
            ON products FOR EACH ROW EXECUTE FUNCTION enforce_product_catalog_domain();

            CREATE FUNCTION enforce_product_variant_catalog_domain() RETURNS trigger AS $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM supplier_skus AS sku
                    WHERE sku.variant_id = NEW.id
                      AND sku.product_id <> NEW.product_id
                ) OR EXISTS (
                    SELECT 1
                    FROM supplier_offers AS offer
                    WHERE offer.variant_id = NEW.id
                      AND offer.product_id <> NEW.product_id
                ) THEN
                    RAISE EXCEPTION 'product variant catalog domain mismatch';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;

            CREATE TRIGGER trg_product_variant_catalog_domain
            BEFORE UPDATE OF product_id
            ON product_variants FOR EACH ROW
            EXECUTE FUNCTION enforce_product_variant_catalog_domain();

            CREATE FUNCTION enforce_supplier_organization_domain() RETURNS trigger AS $$
            BEGIN
                IF NEW.organization_type <> 'SUPPLIER' AND EXISTS (
                    SELECT 1
                    FROM supplier_skus AS sku
                    WHERE sku.supplier_id = NEW.id
                ) THEN
                    RAISE EXCEPTION 'supplier organization domain mismatch';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;

            CREATE TRIGGER trg_supplier_organization_domain
            BEFORE UPDATE OF organization_type
            ON organizations FOR EACH ROW
            EXECUTE FUNCTION enforce_supplier_organization_domain();
            """
        )
    )


def downgrade() -> None:
    connection = op.get_bind()
    oversized_brand_count = connection.execute(
        sa.text(
            """
            SELECT count(*)
            FROM products
            JOIN brands ON brands.id = products.brand_id
            WHERE char_length(brands.name) > 120
            """
        )
    ).scalar_one()
    if oversized_brand_count:
        raise RuntimeError(
            f"{oversized_brand_count} product(s) reference brand names longer than "
            "120 characters; shorten those brand names before downgrade"
        )

    op.execute("DROP TRIGGER trg_supplier_organization_domain ON organizations")
    op.execute("DROP FUNCTION enforce_supplier_organization_domain()")
    op.execute("DROP TRIGGER trg_product_variant_catalog_domain ON product_variants")
    op.execute("DROP FUNCTION enforce_product_variant_catalog_domain()")
    op.execute("DROP TRIGGER trg_product_catalog_domain ON products")
    op.execute("DROP FUNCTION enforce_product_catalog_domain()")
    op.execute("DROP TRIGGER trg_supplier_offer_domain ON supplier_offers")
    op.execute("DROP FUNCTION enforce_supplier_offer_domain()")
    op.execute("DROP TRIGGER trg_supplier_sku_domain ON supplier_skus")
    op.execute("DROP FUNCTION enforce_supplier_sku_domain()")

    op.add_column(
        "products",
        sa.Column("brand", sa.String(length=120), nullable=True),
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
