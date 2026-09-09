"""Replace operator clients with supplier clients.

Deleted credentials cannot be reconstructed in either direction.

Revision ID: 6f4a2b8c9d10
Revises: f3b8a2197c41
Create Date: 2026-09-10
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "6f4a2b8c9d10"
down_revision: str | None = "f3b8a2197c41"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DELETE FROM integration_clients WHERE client_type = 'OPERATOR'")
    op.add_column(
        "integration_clients",
        sa.Column("issuer_user_id", sa.String(length=36), nullable=True),
    )
    op.create_index(
        "ix_integration_clients_issuer_user_id",
        "integration_clients",
        ["issuer_user_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_integration_clients_issuer_user_id_users",
        "integration_clients",
        "users",
        ["issuer_user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_constraint("ck_integration_client_owner", "integration_clients", type_="check")
    op.create_check_constraint(
        "ck_integration_client_owner",
        "integration_clients",
        "(client_type = 'SYSTEM' AND owner_organization_id IS NULL "
        "AND issuer_user_id IS NULL) OR "
        "(client_type = 'SUPPLIER' AND owner_organization_id IS NOT NULL "
        "AND issuer_user_id IS NOT NULL)",
    )


def downgrade() -> None:
    op.execute("DELETE FROM integration_clients WHERE client_type = 'SUPPLIER'")
    op.drop_constraint("ck_integration_client_owner", "integration_clients", type_="check")
    op.drop_constraint(
        "fk_integration_clients_issuer_user_id_users",
        "integration_clients",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_integration_clients_issuer_user_id",
        table_name="integration_clients",
    )
    op.drop_column("integration_clients", "issuer_user_id")
    op.create_check_constraint(
        "ck_integration_client_owner",
        "integration_clients",
        "(client_type = 'SYSTEM' AND owner_organization_id IS NULL) OR "
        "(client_type = 'OPERATOR' AND owner_organization_id IS NOT NULL)",
    )
