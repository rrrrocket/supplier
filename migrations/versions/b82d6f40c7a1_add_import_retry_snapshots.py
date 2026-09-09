"""Add failed-row snapshots for import retries.

Revision ID: b82d6f40c7a1
Revises: a71c4e92b6d3
Create Date: 2026-09-10
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "b82d6f40c7a1"
down_revision: str | None = "a71c4e92b6d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "import_jobs",
        sa.Column(
            "retry_rows",
            sa.JSON(),
            server_default=sa.text("'[]'::json"),
            nullable=False,
        ),
    )
    op.add_column(
        "import_jobs",
        sa.Column("retry_of_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "import_jobs",
        sa.Column(
            "retry_row_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.create_foreign_key(
        "fk_import_jobs_retry_of_id",
        "import_jobs",
        "import_jobs",
        ["retry_of_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_import_jobs_retry_of_id", "import_jobs", ["retry_of_id"])
    op.create_unique_constraint(
        "uq_import_jobs_retry_of_id",
        "import_jobs",
        ["retry_of_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_import_jobs_retry_of_id", "import_jobs", type_="unique")
    op.drop_index("ix_import_jobs_retry_of_id", table_name="import_jobs")
    op.drop_constraint("fk_import_jobs_retry_of_id", "import_jobs", type_="foreignkey")
    op.drop_column("import_jobs", "retry_of_id")
    op.drop_column("import_jobs", "retry_row_count")
    op.drop_column("import_jobs", "retry_rows")
