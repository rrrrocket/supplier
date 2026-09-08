from __future__ import annotations

import subprocess
from uuid import UUID

import pytest

from tests.migration_utils import (
    connect,
    run_downgrade,
    run_migrations,
    temporary_postgresql_database,
)


PREVIOUS_REVISION = "7f22c89a41bd"
CATALOG_REVISION = "9a61d5c312ef"
PRE_CONTRACT_REVISION = "b742e6d423f0"
CONTRACT_REVISION = "cc83f7e534a1"


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


def _insert_contract_fixture(connection, *, missing_brand: bool = False, missing_sku: bool = False) -> None:
    connection.execute(
        """
        INSERT INTO organizations
            (id, code, name, organization_type, is_active, created_at, updated_at)
        VALUES
            ('contract-supplier', 'CONTRACT-SUPPLIER', 'Contract Supplier', 'SUPPLIER',
             true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """
    )
    connection.execute(
        """
        INSERT INTO brands
            (id, code, name, normalized_name, aliases, status, created_at, updated_at)
        VALUES
            ('contract-brand', 'CONTRACT-BRAND', 'Contract Brand', 'contract brand',
             '[]', 'ACTIVE', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """
    )
    connection.execute(
        """
        INSERT INTO products
            (id, created_by_organization_id, name, brand, brand_id, model, category,
             attributes, status, created_at, updated_at)
        VALUES
            ('contract-product', 'contract-supplier', 'Contract Product', 'stale brand',
             %s, 'MODEL-1', 'Test', '{}', 'ACTIVE', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """,
        (None if missing_brand else "contract-brand",),
    )
    if not missing_sku:
        connection.execute(
            """
            INSERT INTO supplier_skus
                (id, supplier_id, brand_id, product_id, supplier_sku_code, status,
                 created_at, updated_at)
            VALUES
                ('contract-sku', 'contract-supplier', 'contract-brand', 'contract-product',
                 'CONTRACT-SKU', 'ACTIVE', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """
        )
    connection.execute(
        """
        INSERT INTO supplier_offers
            (id, organization_id, product_id, supplier_sku, supplier_sku_id, price,
             currency, moq, stock_qty, lead_time_days, fulfillment_mode, status,
             created_at, updated_at)
        VALUES
            ('contract-offer', 'contract-supplier', 'contract-product', 'stale sku', %s,
             10.0000, 'CNY', 1, 5, 3, 'PURCHASE', 'ACTIVE',
             CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """,
        (None if missing_sku else "contract-sku",),
    )


def test_contract_migration_preserves_history_and_enforces_normalized_schema() -> None:
    with temporary_postgresql_database("supplier_catalog_contract") as migration_url:
        database_name = migration_url.database
        assert database_name is not None
        run_migrations(migration_url, PRE_CONTRACT_REVISION)

        with connect(migration_url, database_name) as connection:
            _insert_contract_fixture(connection)
            connection.execute(
                """
                INSERT INTO inventory_snapshots (id, offer_id, quantity, captured_at, source)
                VALUES ('contract-inventory', 'contract-offer', 5, CURRENT_TIMESTAMP, 'MANUAL')
                """
            )

        run_migrations(migration_url, CONTRACT_REVISION)

        with connect(migration_url, database_name) as connection:
            product_columns = dict(
                connection.execute(
                    """
                    SELECT column_name, is_nullable
                    FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'products'
                    """
                )
            )
            offer_columns = dict(
                connection.execute(
                    """
                    SELECT column_name, is_nullable
                    FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'supplier_offers'
                    """
                )
            )
            assert "brand" not in product_columns
            assert product_columns["brand_id"] == "NO"
            assert "supplier_sku" not in offer_columns
            assert offer_columns["supplier_sku_id"] == "NO"
            assert list(
                connection.execute(
                    "SELECT id, brand_id FROM products WHERE id = 'contract-product'"
                )
            ) == [("contract-product", "contract-brand")]
            assert list(
                connection.execute(
                    "SELECT id, supplier_sku_id FROM supplier_offers WHERE id = 'contract-offer'"
                )
            ) == [("contract-offer", "contract-sku")]
            assert list(
                connection.execute(
                    "SELECT id, offer_id FROM inventory_snapshots WHERE id = 'contract-inventory'"
                )
            ) == [("contract-inventory", "contract-offer")]
            constraints = {
                row[0]: tuple(row[1].split(","))
                for row in connection.execute(
                    """
                    SELECT constraint_name,
                           string_agg(column_name::text, ',' ORDER BY ordinal_position)
                    FROM information_schema.key_column_usage
                    WHERE table_schema = 'public'
                      AND table_name IN ('products', 'supplier_offers')
                    GROUP BY constraint_name
                    """
                )
            }
            assert constraints["uq_product_supplier_brand_model_name"] == (
                "created_by_organization_id",
                "brand_id",
                "model",
                "name",
            )
            assert constraints["uq_supplier_offer_supplier_sku_id"] == (
                "supplier_sku_id",
            )


@pytest.mark.parametrize(
    ("missing_brand", "missing_sku", "expected"),
    [
        (True, False, "1 product(s) lack brand_id; 0 supplier offer(s) lack supplier_sku_id"),
        (False, True, "0 product(s) lack brand_id; 1 supplier offer(s) lack supplier_sku_id"),
    ],
)
def test_contract_migration_reports_unresolved_foreign_key_row_counts(
    missing_brand: bool,
    missing_sku: bool,
    expected: str,
) -> None:
    with temporary_postgresql_database("supplier_catalog_contract_missing_fk") as migration_url:
        database_name = migration_url.database
        assert database_name is not None
        run_migrations(migration_url, PRE_CONTRACT_REVISION)
        with connect(migration_url, database_name) as connection:
            _insert_contract_fixture(
                connection,
                missing_brand=missing_brand,
                missing_sku=missing_sku,
            )

        with pytest.raises(subprocess.CalledProcessError) as exc_info:
            run_migrations(migration_url, CONTRACT_REVISION)

        assert expected in exc_info.value.stderr


def test_contract_migration_downgrade_backfills_legacy_display_strings() -> None:
    with temporary_postgresql_database("supplier_catalog_contract_downgrade") as migration_url:
        database_name = migration_url.database
        assert database_name is not None
        run_migrations(migration_url, PRE_CONTRACT_REVISION)
        with connect(migration_url, database_name) as connection:
            _insert_contract_fixture(connection)

        run_migrations(migration_url, CONTRACT_REVISION)
        with connect(migration_url, database_name) as connection:
            connection.execute(
                "UPDATE brands SET name = 'Canonical Brand' WHERE id = 'contract-brand'"
            )
            connection.execute(
                "UPDATE supplier_skus SET supplier_sku_code = 'CANONICAL-SKU' "
                "WHERE id = 'contract-sku'"
            )

        run_downgrade(migration_url, PRE_CONTRACT_REVISION)

        with connect(migration_url, database_name) as connection:
            assert list(
                connection.execute(
                    "SELECT brand FROM products WHERE id = 'contract-product'"
                )
            ) == [("Canonical Brand",)]
            assert list(
                connection.execute(
                    "SELECT supplier_sku FROM supplier_offers WHERE id = 'contract-offer'"
                )
            ) == [("CANONICAL-SKU",)]


def test_complete_upgrade_chain_reaches_contract_revision() -> None:
    with temporary_postgresql_database("supplier_catalog_complete_chain") as migration_url:
        database_name = migration_url.database
        assert database_name is not None

        run_migrations(migration_url, CONTRACT_REVISION)

        with connect(migration_url, database_name) as connection:
            assert connection.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchone()[0] == CONTRACT_REVISION
