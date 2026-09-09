from __future__ import annotations

from tests.migration_utils import (
    connect,
    run_downgrade,
    run_migrations,
    temporary_postgresql_database,
)


PREVIOUS_REVISION = "d14f0c6a7e92"
OPERATOR_REVISION = "f3b8a2197c41"


def test_operator_marketplace_migration_is_reversible_and_backfills_clients() -> None:
    with temporary_postgresql_database("operator_marketplace") as migration_url:
        database_name = migration_url.database
        assert database_name is not None
        run_migrations(migration_url, PREVIOUS_REVISION)

        with connect(migration_url, database_name) as connection:
            connection.execute(
                "INSERT INTO integration_clients "
                "(id, name, token_prefix, token_hash, scopes, is_active) VALUES "
                "('legacy-client', 'Legacy', 'm1i_legacy12', 'hash', '[]', true)"
            )

        run_migrations(migration_url, OPERATOR_REVISION)

        with connect(migration_url, database_name) as connection:
            table_names = {
                row[0]
                for row in connection.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public'"
                )
            }
            assert {
                "operator_applications",
                "operator_profiles",
                "operator_supplier_cooperations",
                "erp_bindings",
            } <= table_names

            client_columns = {
                item[0]: item[1]
                for item in connection.execute(
                    "SELECT column_name, is_nullable FROM information_schema.columns "
                    "WHERE table_name = 'integration_clients'"
                )
            }
            assert client_columns["client_type"] == "NO"
            assert client_columns["owner_organization_id"] == "YES"
            assert connection.execute(
                "SELECT client_type FROM integration_clients WHERE id = 'legacy-client'"
            ).fetchone() == ("SYSTEM",)

            indexes = {
                row[0]: row[1]
                for row in connection.execute(
                    "SELECT indexname, indexdef FROM pg_indexes "
                    "WHERE tablename = 'operator_supplier_cooperations'"
                )
            }
            active_index = indexes["uq_open_operator_supplier_cooperation"]
            assert "UNIQUE" in active_index
            assert "PENDING" in active_index
            assert "ACTIVE" in active_index
            profile_index = connection.execute(
                "SELECT indexdef FROM pg_indexes WHERE tablename = 'operator_profiles' "
                "AND indexname = 'ix_operator_profiles_unified_social_credit_code'"
            ).fetchone()
            assert profile_index is not None
            assert "UNIQUE" in profile_index[0]

        run_downgrade(migration_url, PREVIOUS_REVISION)
        with connect(migration_url, database_name) as connection:
            table_names = {
                row[0]
                for row in connection.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public'"
                )
            }
            assert "operator_applications" not in table_names
            assert "operator_profiles" not in table_names
            client_columns = {
                row[0]
                for row in connection.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'integration_clients'"
                )
            }
            assert "client_type" not in client_columns
            assert "owner_organization_id" not in client_columns

        run_migrations(migration_url, OPERATOR_REVISION)
