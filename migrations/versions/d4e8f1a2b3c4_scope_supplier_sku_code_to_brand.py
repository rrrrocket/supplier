"""Allow the same supplier SKU code under different brands."""

from collections.abc import Sequence

from alembic import op


revision: str = "d4e8f1a2b3c4"
down_revision: str | None = "c91d3e7a2b10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("uq_supplier_sku_code", "supplier_skus", type_="unique")
    op.create_unique_constraint(
        "uq_supplier_brand_sku_code",
        "supplier_skus",
        ["supplier_id", "brand_id", "supplier_sku_code"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_supplier_brand_sku_code", "supplier_skus", type_="unique"
    )
    op.create_unique_constraint(
        "uq_supplier_sku_code",
        "supplier_skus",
        ["supplier_id", "supplier_sku_code"],
    )
