"""Replace operator clients with supplier clients.

Deleted credentials cannot be reconstructed in either direction.

Revision ID: 6f4a2b8c9d10
Revises: f3b8a2197c41
Create Date: 2026-09-10
"""

from collections.abc import Sequence

from alembic import op


revision: str = "6f4a2b8c9d10"
down_revision: str | None = "f3b8a2197c41"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DELETE FROM integration_clients WHERE client_type = 'OPERATOR'")
    op.drop_constraint("ck_integration_client_owner", "integration_clients", type_="check")
    op.create_check_constraint(
        "ck_integration_client_owner",
        "integration_clients",
        "(client_type = 'SYSTEM' AND owner_organization_id IS NULL) OR "
        "(client_type = 'SUPPLIER' AND owner_organization_id IS NOT NULL)",
    )


def downgrade() -> None:
    op.execute("DELETE FROM integration_clients WHERE client_type = 'SUPPLIER'")
    op.drop_constraint("ck_integration_client_owner", "integration_clients", type_="check")
    op.create_check_constraint(
        "ck_integration_client_owner",
        "integration_clients",
        "(client_type = 'SYSTEM' AND owner_organization_id IS NULL) OR "
        "(client_type = 'OPERATOR' AND owner_organization_id IS NOT NULL)",
    )
