from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
from sqlalchemy.engine import URL, make_url


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INITIAL_REVISION = "4d4ef4adb60c"


def connect(database_url: URL, database_name: str) -> psycopg.Connection:
    return psycopg.connect(
        host=database_url.host,
        port=database_url.port,
        user=database_url.username,
        password=database_url.password,
        dbname=database_name,
        autocommit=True,
    )


def run_migrations(database_url: URL, revision: str) -> None:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url.render_as_string(hide_password=False)
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", revision],
        cwd=PROJECT_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )


def test_upgrade_collapses_legacy_supplier_roles_to_supplier() -> None:
    test_server_url = make_url(os.environ["DATABASE_URL"])
    database_name = f"supplier_role_migration_{uuid4().hex}_test"
    migration_url = test_server_url.set(database=database_name)

    with connect(test_server_url, "postgres") as admin_connection:
        admin_connection.execute(
            sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name))
        )

    try:
        run_migrations(migration_url, INITIAL_REVISION)
        with connect(migration_url, database_name) as connection:
            connection.execute(
                """
                INSERT INTO organizations
                    (id, code, name, organization_type, is_active, created_at, updated_at)
                VALUES
                    ('platform-org', 'PLATFORM', '平台组织', 'PLATFORM', true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                    ('supplier-org', 'SUPPLIER', '供应商组织', 'SUPPLIER', true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            )
            with connection.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO users
                        (id, organization_id, email, name, role, password_hash, is_active, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """,
                    [
                        ("platform-user", "platform-org", "platform@example.com", "平台管理员", "PLATFORM_ADMIN", "hash-platform"),
                        ("platform-operator", "platform-org", "platform-operator@example.com", "平台操作员", "OPERATOR", "hash-platform-operator"),
                        ("platform-finance", "platform-org", "platform-finance@example.com", "平台财务", "FINANCE", "hash-platform-finance"),
                        ("supplier-admin", "supplier-org", "admin@example.com", "供应商甲", "SUPPLIER_ADMIN", "hash-admin"),
                        ("supplier-operator", "supplier-org", "operator@example.com", "供应商乙", "OPERATOR", "hash-operator"),
                        ("supplier-finance", "supplier-org", "finance@example.com", "供应商丙", "FINANCE", "hash-finance"),
                    ],
                )

        run_migrations(migration_url, "head")

        with connect(migration_url, database_name) as connection:
            migrated_users = {
                row[0]: tuple(row[1:])
                for row in connection.execute(
                    """
                    SELECT email, id, organization_id, role, password_hash
                    FROM users
                    ORDER BY email
                    """
                )
            }

        assert migrated_users == {
            "admin@example.com": ("supplier-admin", "supplier-org", "SUPPLIER", "hash-admin"),
            "finance@example.com": ("supplier-finance", "supplier-org", "SUPPLIER", "hash-finance"),
            "operator@example.com": ("supplier-operator", "supplier-org", "SUPPLIER", "hash-operator"),
            "platform@example.com": ("platform-user", "platform-org", "PLATFORM_ADMIN", "hash-platform"),
            "platform-finance@example.com": ("platform-finance", "platform-org", "FINANCE", "hash-platform-finance"),
            "platform-operator@example.com": ("platform-operator", "platform-org", "OPERATOR", "hash-platform-operator"),
        }
    finally:
        with connect(test_server_url, "postgres") as admin_connection:
            admin_connection.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s",
                (database_name,),
            )
            admin_connection.execute(
                sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database_name))
            )
