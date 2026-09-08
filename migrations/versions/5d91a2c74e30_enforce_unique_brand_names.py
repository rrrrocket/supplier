"""enforce unique normalized brand names

Revision ID: 5d91a2c74e30
Revises: 3b9f7d2c8a11
Create Date: 2026-09-09 03:30:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "5d91a2c74e30"
down_revision: Union[str, Sequence[str], None] = "3b9f7d2c8a11"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()
    duplicate_rows, duplicate_names = connection.execute(
        sa.text(
            """
            WITH duplicate_groups AS (
                SELECT normalized_name, count(*) AS brand_count
                FROM brands
                GROUP BY normalized_name
                HAVING count(*) > 1
            )
            SELECT coalesce(sum(brand_count), 0), count(*)
            FROM duplicate_groups
            """
        )
    ).one()
    if duplicate_names:
        raise RuntimeError(
            f"{duplicate_rows} duplicate brand row(s) across "
            f"{duplicate_names} normalized name(s); merge duplicates before retrying"
        )

    op.drop_index("ix_brands_normalized_name", table_name="brands")
    op.create_index(
        "ix_brands_normalized_name",
        "brands",
        ["normalized_name"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_brands_normalized_name", table_name="brands")
    op.create_index(
        "ix_brands_normalized_name",
        "brands",
        ["normalized_name"],
        unique=False,
    )
