from __future__ import annotations

from tests.migration_utils import connect, run_migrations, temporary_postgresql_database


EXPAND_REVISION = "9a61d5c312ef"
RECONCILIATION_REVISION = "3b9f7d2c8a11"


def test_reconciliation_migration_repairs_post_expand_legacy_catalog_rows() -> None:
    with temporary_postgresql_database(
        "supplier_catalog_transitional_reconciliation"
    ) as migration_url:
        database_name = migration_url.database
        assert database_name is not None
        run_migrations(migration_url, EXPAND_REVISION)

        with connect(migration_url, database_name) as connection:
            connection.execute(
                """
                INSERT INTO organizations
                    (id, code, name, organization_type, is_active, created_at, updated_at)
                VALUES
                    ('supplier-legacy', 'SUPPLIER-LEGACY', 'Legacy 供应商', 'SUPPLIER',
                     true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            )
            connection.execute(
                """
                INSERT INTO brands
                    (id, code, name, normalized_name, aliases, status,
                     created_at, updated_at)
                VALUES
                    ('brand-canonical', 'BR-CANONICAL', 'Acme', 'acme', '[]', 'ACTIVE',
                     CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            )
            connection.execute(
                """
                INSERT INTO products
                    (id, created_by_organization_id, name, brand, brand_id, model,
                     category, attributes, status, created_at, updated_at)
                VALUES
                    ('product-legacy-a', 'supplier-legacy', 'Legacy 商品 A',
                     '  ACME  ', NULL, 'A-1', '测试', '{}', 'ACTIVE',
                     CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                    ('product-legacy-b', 'supplier-legacy', 'Legacy 商品 B',
                     'Acme', NULL, 'B-1', '测试', '{}', 'ACTIVE',
                     CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                    ('product-legacy-new-brand', 'supplier-legacy', 'Legacy 商品 C',
                     '  New   Brand  ', NULL, 'C-1', '测试', '{}', 'ACTIVE',
                     CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            )
            connection.execute(
                """
                INSERT INTO supplier_offers
                    (id, organization_id, product_id, variant_id, supplier_sku,
                     supplier_sku_id, price, currency, moq, stock_qty,
                     lead_time_days, fulfillment_mode, status, created_at, updated_at)
                VALUES
                    ('offer-legacy-a', 'supplier-legacy', 'product-legacy-a', NULL,
                     'LEGACY-A', NULL, 10.0000, 'CNY', 1, 12, 3, 'PURCHASE', 'ACTIVE',
                     CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                    ('offer-legacy-b', 'supplier-legacy', 'product-legacy-b', NULL,
                     'LEGACY-B', NULL, 20.0000, 'CNY', 2, 23, 5, 'PURCHASE', 'ACTIVE',
                     CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                    ('offer-legacy-c', 'supplier-legacy', 'product-legacy-new-brand', NULL,
                     'LEGACY-C', NULL, 30.0000, 'CNY', 3, 34, 7, 'PURCHASE', 'ACTIVE',
                     CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            )

        run_migrations(migration_url, RECONCILIATION_REVISION)

        with connect(migration_url, database_name) as connection:
            assert list(
                connection.execute(
                    "SELECT id, brand_id FROM products "
                    "WHERE id LIKE 'product-legacy-%' ORDER BY id"
                )
            ) == [
                ("product-legacy-a", "brand-canonical"),
                ("product-legacy-b", "brand-canonical"),
                (
                    "product-legacy-new-brand",
                    connection.execute(
                        "SELECT id FROM brands WHERE normalized_name = 'new brand'"
                    ).fetchone()[0],
                ),
            ]
            assert connection.execute(
                "SELECT count(*) FROM brands WHERE normalized_name = 'acme'"
            ).fetchone()[0] == 1
            assert connection.execute(
                "SELECT count(*) FROM brands WHERE normalized_name = 'new brand'"
            ).fetchone()[0] == 1
            assert connection.execute(
                "SELECT count(*) FROM supplier_brand_cooperations "
                "WHERE supplier_id = 'supplier-legacy' AND status = 'ACTIVE'"
            ).fetchone()[0] == 2
            assert list(
                connection.execute(
                    "SELECT id, supplier_sku_code FROM supplier_skus "
                    "WHERE supplier_id = 'supplier-legacy' ORDER BY id"
                )
            ) == [
                ("offer-legacy-a", "LEGACY-A"),
                ("offer-legacy-b", "LEGACY-B"),
                ("offer-legacy-c", "LEGACY-C"),
            ]
            assert list(
                connection.execute(
                    "SELECT id, product_id, supplier_sku, supplier_sku_id "
                    "FROM supplier_offers WHERE organization_id = 'supplier-legacy' "
                    "ORDER BY id"
                )
            ) == [
                (
                    "offer-legacy-a",
                    "product-legacy-a",
                    "LEGACY-A",
                    "offer-legacy-a",
                ),
                (
                    "offer-legacy-b",
                    "product-legacy-b",
                    "LEGACY-B",
                    "offer-legacy-b",
                ),
                (
                    "offer-legacy-c",
                    "product-legacy-new-brand",
                    "LEGACY-C",
                    "offer-legacy-c",
                ),
            ]
