"""reconcile transitional catalog data

Revision ID: 3b9f7d2c8a11
Revises: 9a61d5c312ef
Create Date: 2026-09-09 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "3b9f7d2c8a11"
down_revision: Union[str, Sequence[str], None] = "9a61d5c312ef"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()
    invalid_brand_count = connection.execute(
        sa.text(
            """
            SELECT count(DISTINCT products.id)
            FROM products
            JOIN supplier_offers ON supplier_offers.product_id = products.id
            WHERE supplier_offers.supplier_sku_id IS NULL
              AND products.brand_id IS NULL
              AND btrim(coalesce(products.brand, '')) = ''
            """
        )
    ).scalar_one()
    if invalid_brand_count:
        raise RuntimeError(
            f"{invalid_brand_count} transitional offered product(s) have an empty brand"
        )

    op.execute(
        sa.text(
            r"""
            WITH normalized_products AS (
                SELECT
                    btrim(brand) AS name,
                    lower(regexp_replace(btrim(brand), '\s+', ' ', 'g')) AS normalized_name
                FROM products
                WHERE brand_id IS NULL
                  AND btrim(coalesce(brand, '')) <> ''
            ), representatives AS (
                SELECT DISTINCT ON (normalized_name) name, normalized_name
                FROM normalized_products
                ORDER BY normalized_name, name
            )
            INSERT INTO brands
                (id, code, name, normalized_name, aliases, status, created_at, updated_at)
            SELECT
                gen_random_uuid()::text,
                'BR-' || upper(substr(md5(representatives.normalized_name), 1, 10)),
                representatives.name,
                representatives.normalized_name,
                '[]'::json,
                'ACTIVE',
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            FROM representatives
            WHERE NOT EXISTS (
                SELECT 1
                FROM brands
                WHERE brands.normalized_name = representatives.normalized_name
            )
            """
        )
    )
    op.execute(
        sa.text(
            r"""
            WITH canonical_brands AS (
                SELECT DISTINCT ON (normalized_name) id, normalized_name
                FROM brands
                ORDER BY normalized_name, created_at, id
            )
            UPDATE products
            SET brand_id = canonical_brands.id
            FROM canonical_brands
            WHERE products.brand_id IS NULL
              AND lower(regexp_replace(btrim(products.brand), '\s+', ' ', 'g')) =
                  canonical_brands.normalized_name
            """
        )
    )

    unresolved_brand_count = connection.execute(
        sa.text(
            """
            SELECT count(DISTINCT products.id)
            FROM products
            JOIN supplier_offers ON supplier_offers.product_id = products.id
            WHERE supplier_offers.supplier_sku_id IS NULL
              AND products.brand_id IS NULL
            """
        )
    ).scalar_one()
    if unresolved_brand_count:
        raise RuntimeError(
            f"{unresolved_brand_count} transitional offered product(s) could not resolve a brand"
        )

    op.execute(
        sa.text(
            """
            WITH required_cooperations AS (
                SELECT DISTINCT
                    offers.organization_id AS supplier_id,
                    products.brand_id
                FROM supplier_offers AS offers
                JOIN products ON products.id = offers.product_id
                WHERE offers.supplier_sku_id IS NULL
                  AND products.brand_id IS NOT NULL
            )
            INSERT INTO supplier_brand_cooperations
                (id, supplier_id, brand_id, commercial_mode, status,
                 valid_from, valid_to, notes, created_at, updated_at)
            SELECT
                gen_random_uuid()::text,
                required_cooperations.supplier_id,
                required_cooperations.brand_id,
                'SELF_PURCHASE',
                'ACTIVE',
                NULL::date,
                NULL::date,
                NULL::text,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            FROM required_cooperations
            WHERE NOT EXISTS (
                SELECT 1
                FROM supplier_brand_cooperations AS cooperation
                WHERE cooperation.supplier_id = required_cooperations.supplier_id
                  AND cooperation.brand_id = required_cooperations.brand_id
                  AND cooperation.status = 'ACTIVE'
            )
            """
        )
    )

    invalid_owner_count = connection.execute(
        sa.text(
            """
            SELECT count(*)
            FROM supplier_offers AS offers
            JOIN products ON products.id = offers.product_id
            WHERE offers.supplier_sku_id IS NULL
              AND offers.organization_id <> products.created_by_organization_id
            """
        )
    ).scalar_one()
    if invalid_owner_count:
        raise RuntimeError(
            f"{invalid_owner_count} transitional offer(s) do not belong to the product supplier"
        )

    conflicting_identity_count = connection.execute(
        sa.text(
            """
            SELECT count(*)
            FROM supplier_offers AS offers
            JOIN products ON products.id = offers.product_id
            JOIN supplier_skus AS supplier_skus
              ON supplier_skus.supplier_id = offers.organization_id
             AND supplier_skus.supplier_sku_code = offers.supplier_sku
            WHERE offers.supplier_sku_id IS NULL
              AND (
                  supplier_skus.brand_id <> products.brand_id
                  OR supplier_skus.product_id <> offers.product_id
                  OR supplier_skus.variant_id IS DISTINCT FROM offers.variant_id
              )
            """
        )
    ).scalar_one()
    if conflicting_identity_count:
        raise RuntimeError(
            f"{conflicting_identity_count} transitional offer(s) conflict with an existing supplier SKU"
        )

    occupied_id_count = connection.execute(
        sa.text(
            """
            SELECT count(*)
            FROM supplier_offers AS offers
            JOIN supplier_skus AS supplier_skus ON supplier_skus.id = offers.id
            WHERE offers.supplier_sku_id IS NULL
              AND (
                  supplier_skus.supplier_id <> offers.organization_id
                  OR supplier_skus.supplier_sku_code <> offers.supplier_sku
              )
            """
        )
    ).scalar_one()
    if occupied_id_count:
        raise RuntimeError(
            f"{occupied_id_count} transitional offer ID(s) conflict with an existing supplier SKU"
        )

    linked_supplier_sku_count = connection.execute(
        sa.text(
            """
            SELECT count(*)
            FROM supplier_offers AS transitional_offer
            JOIN supplier_skus AS supplier_skus
              ON supplier_skus.supplier_id = transitional_offer.organization_id
             AND supplier_skus.supplier_sku_code = transitional_offer.supplier_sku
            JOIN supplier_offers AS linked_offer
              ON linked_offer.supplier_sku_id = supplier_skus.id
             AND linked_offer.id <> transitional_offer.id
            WHERE transitional_offer.supplier_sku_id IS NULL
            """
        )
    ).scalar_one()
    if linked_supplier_sku_count:
        raise RuntimeError(
            f"{linked_supplier_sku_count} transitional offer(s) reuse an already linked supplier SKU"
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
            WHERE offers.supplier_sku_id IS NULL
              AND NOT EXISTS (
                  SELECT 1
                  FROM supplier_skus
                  WHERE supplier_skus.supplier_id = offers.organization_id
                    AND supplier_skus.supplier_sku_code = offers.supplier_sku
              )
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE supplier_offers AS offers
            SET supplier_sku_id = supplier_skus.id
            FROM supplier_skus, products
            WHERE offers.supplier_sku_id IS NULL
              AND products.id = offers.product_id
              AND supplier_skus.supplier_id = offers.organization_id
              AND supplier_skus.supplier_sku_code = offers.supplier_sku
              AND supplier_skus.brand_id = products.brand_id
              AND supplier_skus.product_id = offers.product_id
              AND supplier_skus.variant_id IS NOT DISTINCT FROM offers.variant_id
            """
        )
    )

    unresolved_offer_count = connection.execute(
        sa.text(
            """
            SELECT count(*)
            FROM supplier_offers
            WHERE supplier_sku_id IS NULL
            """
        )
    ).scalar_one()
    if unresolved_offer_count:
        raise RuntimeError(
            f"{unresolved_offer_count} transitional offer(s) could not resolve a supplier SKU"
        )


def downgrade() -> None:
    pass
