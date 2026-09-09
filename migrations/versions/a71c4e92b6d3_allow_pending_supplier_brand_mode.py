"""Allow supplier brand cooperation mode to be configured later.

Revision ID: a71c4e92b6d3
Revises: 6f4a2b8c9d10
Create Date: 2026-09-10
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "a71c4e92b6d3"
down_revision: str | None = "6f4a2b8c9d10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "supplier_brand_cooperations",
        "commercial_mode",
        existing_type=sa.String(length=40),
        nullable=True,
    )
    op.add_column(
        "import_jobs",
        sa.Column(
            "error_summary",
            sa.JSON(),
            server_default=sa.text("'[]'::json"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("import_jobs", "error_summary")
    op.execute(
        "UPDATE supplier_brand_cooperations "
        "SET commercial_mode = 'SELF_PURCHASE' WHERE commercial_mode IS NULL"
    )
    op.alter_column(
        "supplier_brand_cooperations",
        "commercial_mode",
        existing_type=sa.String(length=40),
        nullable=False,
    )
