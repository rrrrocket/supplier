"""Default supplier brand cooperation mode to self-purchase (A).

Revision ID: c91d3e7a2b10
Revises: b82d6f40c7a1
Create Date: 2026-09-17
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "c91d3e7a2b10"
down_revision: str | None = "b82d6f40c7a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE supplier_brand_cooperations "
            "SET commercial_mode = 'SELF_PURCHASE' "
            "WHERE commercial_mode IS NULL"
        )
    )


def downgrade() -> None:
    # A mode is now the intentional default; do not erase existing choices.
    pass
