from __future__ import annotations

import subprocess
from uuid import UUID

import pytest

from tests.migration_utils import connect, run_migrations, temporary_postgresql_database


PREVIOUS_REVISION = "7f22c89a41bd"
CATALOG_REVISION = "9a61d5c312ef"


def test_catalog_migration_rejects_offered_products_with_empty_brands() -> None:
    with temporary_postgresql_database("supplier_catalog_empty_brand") as migration_url:
        database_name = migration_url.database
        assert database_name is not None
        run_migrations(migration_url, PREVIOUS_REVISION)

        with connect(migration_url, database_name) as connection:
            connection.execute(
                """
                INSERT INTO organizations
                    (id, code, name, organization_type, is_active, created_at, updated_at)
                VALUES
                    ('supplier-org', 'SUPPLIER-1', '供应商甲', 'SUPPLIER', true,
                     CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            )
            connection.execute(
                """
                INSERT INTO products
                    (id, created_by_organization_id, name, brand, category,
                     attributes, status, created_at, updated_at)
                VALUES
                    ('product-empty-brand', 'supplier-org', '无品牌商品', '   ', '测试',
                     '{}', 'ACTIVE', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            )
            connection.execute(
                """
                INSERT INTO supplier_offers
                    (id, organization_id, product_id, supplier_sku, price,
                     currency, moq, stock_qty, lead_time_days, fulfillment_mode,
                     status, created_at, updated_at)
                VALUES
                    ('offer-empty-brand', 'supplier-org', 'product-empty-brand',
                     'SKU-EMPTY', 10.0000, 'CNY', 1, 0, 3, 'PURCHASE', 'ACTIVE',
                     CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            )

        with pytest.raises(subprocess.CalledProcessError) as exc_info:
            run_migrations(migration_url, CATALOG_REVISION)

        assert "1 offered product(s) have an empty brand" in exc_info.value.stderr


def test_catalog_migration_creates_one_active_cooperation_for_multiple_brand_offers() -> None:
    with temporary_postgresql_database("supplier_catalog_duplicate_cooperation") as migration_url:
        database_name = migration_url.database
        assert database_name is not None
        run_migrations(migration_url, PREVIOUS_REVISION)

        with connect(migration_url, database_name) as connection:
            connection.execute(
                """
                INSERT INTO organizations
                    (id, code, name, organization_type, is_active, created_at, updated_at)
                VALUES
                    ('supplier-org', 'SUPPLIER-1', '供应商甲', 'SUPPLIER', true,
                     CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            )
            connection.execute(
                """
                INSERT INTO products
                    (id, created_by_organization_id, name, brand, category,
                     attributes, status, created_at, updated_at)
                VALUES
                    ('product-a', 'supplier-org', '商品A', '品牌A', '测试',
                     '{}', 'ACTIVE', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            )
            connection.execute(
                """
                INSERT INTO supplier_offers
                    (id, organization_id, product_id, supplier_sku, price,
                     currency, moq, stock_qty, lead_time_days, fulfillment_mode,
                     status, created_at, updated_at)
                VALUES
                    ('offer-a-1', 'supplier-org', 'product-a', 'SKU-A-1', 10.0000,
                     'CNY', 1, 12, 3, 'PURCHASE', 'ACTIVE',
                     CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                    ('offer-a-2', 'supplier-org', 'product-a', 'SKU-A-2', 11.0000,
                     'CNY', 1, 10, 3, 'PURCHASE', 'ACTIVE',
                     CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            )

        run_migrations(migration_url, CATALOG_REVISION)

        with connect(migration_url, database_name) as connection:
            assert connection.execute(
                "SELECT count(*) FROM supplier_brand_cooperations "
                "WHERE supplier_id = 'supplier-org' AND status = 'ACTIVE'"
            ).fetchone()[0] == 1


def test_catalog_migration_backfills_new_identities_without_changing_legacy_data() -> None:
    with temporary_postgresql_database("supplier_catalog_migration") as migration_url:
        database_name = migration_url.database
        assert database_name is not None
        run_migrations(migration_url, PREVIOUS_REVISION)

        with connect(migration_url, database_name) as connection:
            connection.execute(
                """
                INSERT INTO organizations
                    (id, code, name, organization_type, is_active, created_at, updated_at)
                VALUES
                    ('supplier-org', 'SUPPLIER-1', '供应商甲', 'SUPPLIER', true,
                     CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            )
            connection.execute(
                """
                INSERT INTO products
                    (id, created_by_organization_id, name, brand, model, category,
                     attributes, status, created_at, updated_at)
                VALUES
                    ('product-a', 'supplier-org', '商品A', '品牌A', 'A-1', '测试',
                     '{}', 'ACTIVE', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                    ('product-b', 'supplier-org', '商品B', '品牌B', 'B-1', '测试',
                     '{}', 'ACTIVE', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            )
            connection.execute(
                """
                INSERT INTO supplier_offers
                    (id, organization_id, product_id, variant_id, supplier_sku,
                     price, currency, moq, stock_qty, lead_time_days,
                     fulfillment_mode, status, created_at, updated_at)
                VALUES
                    ('offer-a', 'supplier-org', 'product-a', NULL, 'SKU-A',
                     10.0000, 'CNY', 1, 12, 3, 'PURCHASE', 'ACTIVE',
                     CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                    ('offer-b', 'supplier-org', 'product-b', NULL, 'SKU-B',
                     20.0000, 'CNY', 2, 23, 5, 'PURCHASE', 'ACTIVE',
                     CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            )
            connection.execute(
                """
                INSERT INTO inventory_snapshots
                    (id, offer_id, quantity, captured_at, source)
                VALUES
                    ('inventory-a', 'offer-a', 12, CURRENT_TIMESTAMP, 'MANUAL')
                """
            )

        run_migrations(migration_url, CATALOG_REVISION)

        with connect(migration_url, database_name) as connection:
            brand_ids = [row[0] for row in connection.execute("SELECT id FROM brands")]
            cooperation_ids = [
                row[0]
                for row in connection.execute(
                    "SELECT id FROM supplier_brand_cooperations"
                )
            ]
            assert [str(UUID(value)) for value in brand_ids] == brand_ids
            assert [str(UUID(value)) for value in cooperation_ids] == cooperation_ids
            assert connection.execute("SELECT count(*) FROM brands").fetchone()[0] == 2
            assert dict(
                connection.execute(
                    "SELECT name, commercial_mode FROM brands "
                    "JOIN supplier_brand_cooperations "
                    "ON brands.id = supplier_brand_cooperations.brand_id"
                )
            ) == {"品牌A": "SELF_PURCHASE", "品牌B": "SELF_PURCHASE"}
            assert connection.execute(
                "SELECT count(*) FROM supplier_skus"
            ).fetchone()[0] == 2
            assert connection.execute(
                "SELECT count(*) FROM supplier_offers "
                "WHERE supplier_sku_id IS NOT NULL"
            ).fetchone()[0] == 2
            assert connection.execute(
                "SELECT count(*) FROM inventory_snapshots"
            ).fetchone()[0] == 1

            assert list(
                connection.execute(
                    "SELECT id, supplier_sku_code FROM supplier_skus ORDER BY id"
                )
            ) == [("offer-a", "SKU-A"), ("offer-b", "SKU-B")]
            assert list(
                connection.execute(
                    "SELECT id, organization_id, product_id, supplier_sku_id "
                    "FROM supplier_offers ORDER BY id"
                )
            ) == [
                ("offer-a", "supplier-org", "product-a", "offer-a"),
                ("offer-b", "supplier-org", "product-b", "offer-b"),
            ]
            assert list(
                connection.execute(
                    "SELECT id, created_by_organization_id FROM products ORDER BY id"
                )
            ) == [
                ("product-a", "supplier-org"),
                ("product-b", "supplier-org"),
            ]
            assert list(
                connection.execute("SELECT id, offer_id FROM inventory_snapshots")
            ) == [("inventory-a", "offer-a")]
