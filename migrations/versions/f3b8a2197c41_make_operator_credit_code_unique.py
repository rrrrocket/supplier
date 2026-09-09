"""make operator credit code unique

Revision ID: f3b8a2197c41
Revises: e8c4a91d2f70
Create Date: 2026-09-09
"""

from collections.abc import Sequence

from alembic import op


revision: str = "f3b8a2197c41"
down_revision: str | None = "e8c4a91d2f70"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_operator_profiles_unified_social_credit_code", table_name="operator_profiles")
    op.create_index(
        "ix_operator_profiles_unified_social_credit_code",
        "operator_profiles",
        ["unified_social_credit_code"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_operator_profiles_unified_social_credit_code", table_name="operator_profiles")
    op.create_index(
        "ix_operator_profiles_unified_social_credit_code",
        "operator_profiles",
        ["unified_social_credit_code"],
        unique=False,
    )
