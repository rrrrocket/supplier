from __future__ import annotations

import subprocess

import psycopg
import pytest

from tests.migration_utils import connect, run_migrations, temporary_postgresql_database


PREVIOUS_REVISION = "3b9f7d2c8a11"
UNIQUE_BRAND_REVISION = "5d91a2c74e30"


def test_unique_brand_migration_rejects_existing_normalized_name_duplicates() -> None:
    with temporary_postgresql_database("duplicate_normalized_brands") as migration_url:
        database_name = migration_url.database
        assert database_name is not None
        run_migrations(migration_url, PREVIOUS_REVISION)

        with connect(migration_url, database_name) as connection:
            connection.execute(
                """
                INSERT INTO brands
                    (id, code, name, normalized_name, aliases, status,
                     created_at, updated_at)
                VALUES
                    ('duplicate-brand-a', 'DUP-A', 'Acme', 'acme', '[]', 'ACTIVE',
                     CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                    ('duplicate-brand-b', 'DUP-B', ' ACME ', 'acme', '[]', 'ACTIVE',
                     CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            )

        with pytest.raises(subprocess.CalledProcessError) as exc_info:
            run_migrations(migration_url, UNIQUE_BRAND_REVISION)

        assert (
            "2 duplicate brand row(s) across 1 normalized name(s)"
            in exc_info.value.stderr
        )


def test_unique_brand_migration_enforces_normalized_name_uniqueness() -> None:
    with temporary_postgresql_database("unique_normalized_brands") as migration_url:
        database_name = migration_url.database
        assert database_name is not None
        run_migrations(migration_url, UNIQUE_BRAND_REVISION)

        with connect(migration_url, database_name) as connection:
            connection.execute(
                """
                INSERT INTO brands
                    (id, code, name, normalized_name, aliases, status,
                     created_at, updated_at)
                VALUES
                    ('unique-brand-a', 'UNIQUE-A', 'Acme', 'acme', '[]', 'ACTIVE',
                     CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            )
            with pytest.raises(psycopg.errors.UniqueViolation):
                connection.execute(
                    """
                    INSERT INTO brands
                        (id, code, name, normalized_name, aliases, status,
                         created_at, updated_at)
                    VALUES
                        ('unique-brand-b', 'UNIQUE-B', 'ACME', 'acme', '[]', 'ACTIVE',
                         CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """
                )
