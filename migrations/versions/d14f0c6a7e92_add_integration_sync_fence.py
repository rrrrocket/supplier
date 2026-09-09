"""add commit-safe integration sync fence

Revision ID: d14f0c6a7e92
Revises: cc83f7e534a1
Create Date: 2026-09-09 23:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "d14f0c6a7e92"
down_revision: Union[str, Sequence[str], None] = "cc83f7e534a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


FENCED_TABLES = (
    "organizations",
    "supplier_profiles",
    "brands",
    "supplier_brand_cooperations",
    "supplier_skus",
    "products",
)


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            CREATE FUNCTION fence_integration_sync_write() RETURNS trigger AS $$
            BEGIN
                PERFORM pg_advisory_xact_lock_shared(763295864120260909);
                NEW.updated_at := clock_timestamp();
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
    )
    for table_name in FENCED_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER trg_integration_sync_fence
            BEFORE INSERT OR UPDATE ON {table_name}
            FOR EACH ROW EXECUTE FUNCTION fence_integration_sync_write()
            """
        )


def downgrade() -> None:
    for table_name in reversed(FENCED_TABLES):
        op.execute(f"DROP TRIGGER trg_integration_sync_fence ON {table_name}")
    op.execute("DROP FUNCTION fence_integration_sync_write()")
