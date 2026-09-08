from tests.migration_utils import connect, run_migrations, temporary_postgresql_database


INITIAL_REVISION = "4d4ef4adb60c"


def test_upgrade_collapses_legacy_supplier_roles_to_supplier() -> None:
    with temporary_postgresql_database("supplier_role_migration") as migration_url:
        database_name = migration_url.database
        assert database_name is not None
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
