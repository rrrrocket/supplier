from __future__ import annotations

import psycopg
import pytest

from tests.migration_utils import (
    connect,
    run_downgrade,
    run_migrations,
    temporary_postgresql_database,
)


PREVIOUS_REVISION = "f3b8a2197c41"
SUPPLIER_CLIENT_REVISION = "6f4a2b8c9d10"


def test_supplier_client_migration_persists_issuer_and_deletes_credentials_with_user() -> None:
    with temporary_postgresql_database("supplier_client_issuer") as migration_url:
        database_name = migration_url.database
        assert database_name is not None
        run_migrations(migration_url, PREVIOUS_REVISION)
        with connect(migration_url, database_name) as connection:
            connection.execute(
                "INSERT INTO organizations "
                "(id, code, name, organization_type, is_active, created_at, updated_at) "
                "VALUES ('supplier-owner', 'SUP-ISSUER', '供应商', 'SUPPLIER', true, now(), now())"
            )
            connection.execute(
                "INSERT INTO users "
                "(id, organization_id, email, name, role, password_hash, is_active, "
                "created_at, updated_at) VALUES "
                "('supplier-issuer', 'supplier-owner', 'issuer@example.com', '签发人', "
                "'SUPPLIER', 'hash', true, now(), now())"
            )

        run_migrations(migration_url, SUPPLIER_CLIENT_REVISION)

        with connect(migration_url, database_name) as connection:
            assert connection.execute(
                "SELECT column_name, is_nullable FROM information_schema.columns "
                "WHERE table_name = 'integration_clients' AND column_name = 'issuer_user_id'"
            ).fetchall() == [("issuer_user_id", "YES")]
            assert connection.execute(
                "SELECT delete_rule FROM information_schema.referential_constraints "
                "WHERE constraint_name = 'fk_integration_clients_issuer_user_id_users'"
            ).fetchall() == [("CASCADE",)]

            connection.execute(
                "INSERT INTO integration_clients "
                "(id, name, client_type, owner_organization_id, issuer_user_id, "
                "token_prefix, token_hash, scopes, is_active) VALUES "
                "('supplier-client', 'Supplier', 'SUPPLIER', 'supplier-owner', "
                "'supplier-issuer', 'm1i_supplie0', 'hash', '[]', true)"
            )
            connection.execute("DELETE FROM users WHERE id = 'supplier-issuer'")
            assert connection.execute(
                "SELECT id FROM integration_clients WHERE id = 'supplier-client'"
            ).fetchall() == []


@pytest.mark.parametrize(
    ("client_type", "owner_id", "issuer_id"),
    [
        ("SUPPLIER", "supplier-owner", None),
        ("SYSTEM", None, "supplier-issuer"),
        ("SYSTEM", "supplier-owner", None),
        ("OPERATOR", "supplier-owner", "supplier-issuer"),
    ],
    ids=[
        "supplier-without-issuer",
        "system-with-issuer",
        "system-with-owner",
        "operator-after-upgrade",
    ],
)
def test_supplier_client_migration_rejects_invalid_client_ownership(
    client_type: str,
    owner_id: str | None,
    issuer_id: str | None,
) -> None:
    with temporary_postgresql_database("supplier_client_issuer_constraint") as migration_url:
        database_name = migration_url.database
        assert database_name is not None
        run_migrations(migration_url, PREVIOUS_REVISION)
        with connect(migration_url, database_name) as connection:
            connection.execute(
                "INSERT INTO organizations "
                "(id, code, name, organization_type, is_active, created_at, updated_at) "
                "VALUES ('supplier-owner', 'SUP-ISSUER', '供应商', 'SUPPLIER', true, now(), now())"
            )
            connection.execute(
                "INSERT INTO users "
                "(id, organization_id, email, name, role, password_hash, is_active, "
                "created_at, updated_at) VALUES "
                "('supplier-issuer', 'supplier-owner', 'issuer@example.com', '签发人', "
                "'SUPPLIER', 'hash', true, now(), now())"
            )
        run_migrations(migration_url, SUPPLIER_CLIENT_REVISION)

        with connect(migration_url, database_name) as connection:
            with pytest.raises(psycopg.errors.CheckViolation):
                connection.execute(
                    "INSERT INTO integration_clients "
                    "(id, name, client_type, owner_organization_id, issuer_user_id, "
                    "token_prefix, token_hash, scopes, is_active) VALUES "
                    "('invalid-client', 'Invalid', %s, %s, %s, "
                    "'m1i_invalid0', 'hash', '[]', true)",
                    (client_type, owner_id, issuer_id),
                )


def test_supplier_client_migration_deletes_operator_clients_and_replaces_constraint() -> None:
    with temporary_postgresql_database("supplier_clients") as migration_url:
        database_name = migration_url.database
        assert database_name is not None
        run_migrations(migration_url, PREVIOUS_REVISION)
        with connect(migration_url, database_name) as connection:
            connection.execute(
                "INSERT INTO organizations (id, code, name, organization_type, is_active, created_at, updated_at) "
                "VALUES ('supplier-owner', 'SUP-OWNER', '供应商', 'SUPPLIER', true, now(), now())"
            )
            connection.execute(
                "INSERT INTO users "
                "(id, organization_id, email, name, role, password_hash, is_active, "
                "created_at, updated_at) VALUES "
                "('supplier-issuer', 'supplier-owner', 'issuer@example.com', '签发人', "
                "'SUPPLIER', 'hash', true, now(), now())"
            )
            connection.execute(
                "INSERT INTO integration_clients "
                "(id, name, client_type, owner_organization_id, token_prefix, token_hash, scopes, is_active) VALUES "
                "('system-client', 'System', 'SYSTEM', NULL, 'm1i_system00', 'hash', '[]', true), "
                "('operator-client', 'Operator', 'OPERATOR', 'supplier-owner', 'm1i_operatr0', 'hash', '[]', true)"
            )
        run_migrations(migration_url, SUPPLIER_CLIENT_REVISION)
        with connect(migration_url, database_name) as connection:
            assert connection.execute(
                "SELECT id FROM integration_clients ORDER BY id"
            ).fetchall() == [("system-client",)]
            connection.execute(
                "INSERT INTO integration_clients "
                "(id, name, client_type, owner_organization_id, issuer_user_id, "
                "token_prefix, token_hash, scopes, is_active) "
                "VALUES ('supplier-client', 'Supplier', 'SUPPLIER', 'supplier-owner', "
                "'supplier-issuer', 'm1i_supplie0', 'hash', '[]', true)"
            )
            with pytest.raises(psycopg.errors.CheckViolation):
                connection.execute(
                    "INSERT INTO integration_clients "
                    "(id, name, client_type, owner_organization_id, issuer_user_id, "
                    "token_prefix, token_hash, scopes, is_active) "
                    "VALUES ('invalid-client', 'Invalid', 'SUPPLIER', NULL, "
                    "'supplier-issuer', 'm1i_invalid0', 'hash', '[]', true)"
                )


def test_supplier_client_migration_downgrade_does_not_reconstruct_deleted_credentials() -> None:
    with temporary_postgresql_database("supplier_client_downgrade") as migration_url:
        database_name = migration_url.database
        assert database_name is not None
        run_migrations(migration_url, PREVIOUS_REVISION)
        with connect(migration_url, database_name) as connection:
            connection.execute(
                "INSERT INTO organizations (id, code, name, organization_type, is_active, created_at, updated_at) "
                "VALUES ('supplier-owner', 'SUP-OWNER', '供应商', 'SUPPLIER', true, now(), now())"
            )
            connection.execute(
                "INSERT INTO users "
                "(id, organization_id, email, name, role, password_hash, is_active, "
                "created_at, updated_at) VALUES "
                "('supplier-issuer', 'supplier-owner', 'issuer@example.com', '签发人', "
                "'SUPPLIER', 'hash', true, now(), now())"
            )
            connection.execute(
                "INSERT INTO integration_clients "
                "(id, name, client_type, owner_organization_id, token_prefix, token_hash, scopes, is_active) VALUES "
                "('system-client', 'System', 'SYSTEM', NULL, 'm1i_system00', 'hash', '[]', true), "
                "('operator-client', 'Operator', 'OPERATOR', 'supplier-owner', 'm1i_operatr0', 'hash', '[]', true)"
            )
        run_migrations(migration_url, SUPPLIER_CLIENT_REVISION)
        with connect(migration_url, database_name) as connection:
            connection.execute(
                "INSERT INTO integration_clients "
                "(id, name, client_type, owner_organization_id, issuer_user_id, "
                "token_prefix, token_hash, scopes, is_active) "
                "VALUES ('supplier-client', 'Supplier', 'SUPPLIER', 'supplier-owner', "
                "'supplier-issuer', 'm1i_supplie0', 'hash', '[]', true)"
            )

        run_downgrade(migration_url, PREVIOUS_REVISION)
        with connect(migration_url, database_name) as connection:
            assert connection.execute(
                "SELECT id FROM integration_clients ORDER BY id"
            ).fetchall() == [("system-client",)]
            connection.execute(
                "INSERT INTO integration_clients "
                "(id, name, client_type, owner_organization_id, token_prefix, token_hash, scopes, is_active) "
                "VALUES ('new-operator-client', 'Operator', 'OPERATOR', 'supplier-owner', "
                "'m1i_newopert', 'hash', '[]', true)"
            )
