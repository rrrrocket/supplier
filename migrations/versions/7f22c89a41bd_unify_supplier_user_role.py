"""unify supplier user role

Revision ID: 7f22c89a41bd
Revises: 4d4ef4adb60c
Create Date: 2026-09-08 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "7f22c89a41bd"
down_revision: Union[str, Sequence[str], None] = "4d4ef4adb60c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE users
            SET role = 'SUPPLIER'
            WHERE role IN ('SUPPLIER_ADMIN', 'OPERATOR', 'FINANCE')
              AND organization_id IN (
                  SELECT id
                  FROM organizations
                  WHERE organization_type = 'SUPPLIER'
              )
            """
        )
    )


def downgrade() -> None:
    # The legacy supplier sub-roles cannot be reconstructed after consolidation.
    op.execute(
        sa.text(
            """
            UPDATE users
            SET role = 'SUPPLIER_ADMIN'
            WHERE role = 'SUPPLIER'
              AND organization_id IN (
                  SELECT id
                  FROM organizations
                  WHERE organization_type = 'SUPPLIER'
              )
            """
        )
    )
