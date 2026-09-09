"""add operator marketplace

Revision ID: e8c4a91d2f70
Revises: d14f0c6a7e92
Create Date: 2026-09-09 17:30:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "e8c4a91d2f70"
down_revision: Union[str, Sequence[str], None] = "d14f0c6a7e92"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def timestamp_columns() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.add_column(
        "integration_clients",
        sa.Column("client_type", sa.String(30), server_default="SYSTEM", nullable=False),
    )
    op.add_column(
        "integration_clients",
        sa.Column("owner_organization_id", sa.String(36), nullable=True),
    )
    op.create_foreign_key(
        "fk_integration_clients_owner_organization_id",
        "integration_clients",
        "organizations",
        ["owner_organization_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_integration_clients_owner_organization_id",
        "integration_clients",
        ["owner_organization_id"],
    )
    op.create_check_constraint(
        "ck_integration_client_owner",
        "integration_clients",
        "(client_type = 'SYSTEM' AND owner_organization_id IS NULL) OR "
        "(client_type = 'OPERATOR' AND owner_organization_id IS NOT NULL)",
    )

    op.create_table(
        "operator_applications",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("application_no", sa.String(32), nullable=False),
        sa.Column("contact_name", sa.String(100), nullable=False),
        sa.Column("phone", sa.String(60), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("company_name", sa.String(240)),
        sa.Column("unified_social_credit_code", sa.String(40)),
        sa.Column("operator_type", sa.String(80)),
        sa.Column("province", sa.String(80)),
        sa.Column("city", sa.String(80)),
        sa.Column("website", sa.String(255)),
        sa.Column("erp_name", sa.String(120)),
        sa.Column("sales_channels", sa.JSON(), nullable=False),
        sa.Column("categories", sa.JSON(), nullable=False),
        sa.Column("target_markets", sa.JSON(), nullable=False),
        sa.Column("qualification_files", sa.JSON(), nullable=False),
        sa.Column("message", sa.Text()),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("review_notes", sa.Text()),
        sa.Column("approved_organization_id", sa.String(36)),
        sa.Column("reviewed_by_user_id", sa.String(36)),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(["approved_organization_id"], ["organizations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("application_no"),
    )
    for column in ("application_no", "email", "unified_social_credit_code", "status", "approved_organization_id", "reviewed_by_user_id"):
        op.create_index(f"ix_operator_applications_{column}", "operator_applications", [column])

    op.create_table(
        "operator_profiles",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("company_name", sa.String(240)),
        sa.Column("unified_social_credit_code", sa.String(40)),
        sa.Column("operator_type", sa.String(80)),
        sa.Column("province", sa.String(80)),
        sa.Column("city", sa.String(80)),
        sa.Column("contact_name", sa.String(100), nullable=False),
        sa.Column("contact_phone", sa.String(60), nullable=False),
        sa.Column("contact_email", sa.String(255), nullable=False),
        sa.Column("website", sa.String(255)),
        sa.Column("erp_name", sa.String(120)),
        sa.Column("sales_channels", sa.JSON(), nullable=False),
        sa.Column("categories", sa.JSON(), nullable=False),
        sa.Column("target_markets", sa.JSON(), nullable=False),
        sa.Column("qualification_files", sa.JSON(), nullable=False),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id"),
    )
    op.create_index("ix_operator_profiles_organization_id", "operator_profiles", ["organization_id"], unique=True)
    op.create_index("ix_operator_profiles_unified_social_credit_code", "operator_profiles", ["unified_social_credit_code"])

    op.create_table(
        "operator_supplier_cooperations",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("operator_id", sa.String(36), nullable=False),
        sa.Column("supplier_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("categories", sa.JSON(), nullable=False),
        sa.Column("brands", sa.JSON(), nullable=False),
        sa.Column("sales_channels", sa.JSON(), nullable=False),
        sa.Column("target_markets", sa.JSON(), nullable=False),
        sa.Column("message", sa.Text()),
        sa.Column("response_notes", sa.Text()),
        sa.Column("requested_by_user_id", sa.String(36), nullable=False),
        sa.Column("responded_by_user_id", sa.String(36)),
        sa.Column("responded_at", sa.DateTime(timezone=True)),
        sa.Column("terminated_by_user_id", sa.String(36)),
        sa.Column("terminated_at", sa.DateTime(timezone=True)),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(["operator_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["supplier_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["responded_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["terminated_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("operator_id", "supplier_id", "status", "requested_by_user_id", "responded_by_user_id", "terminated_by_user_id"):
        op.create_index(f"ix_operator_supplier_cooperations_{column}", "operator_supplier_cooperations", [column])
    op.create_index(
        "uq_open_operator_supplier_cooperation",
        "operator_supplier_cooperations",
        ["operator_id", "supplier_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('PENDING', 'ACTIVE')"),
    )

    op.create_table(
        "erp_bindings",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("cooperation_id", sa.String(36), nullable=False),
        sa.Column("operator_id", sa.String(36), nullable=False),
        sa.Column("supplier_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("bound_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("unbound_at", sa.DateTime(timezone=True)),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(["cooperation_id"], ["operator_supplier_cooperations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["operator_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["supplier_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cooperation_id"),
    )
    op.create_index("ix_erp_bindings_cooperation_id", "erp_bindings", ["cooperation_id"], unique=True)
    for column in ("operator_id", "supplier_id", "status"):
        op.create_index(f"ix_erp_bindings_{column}", "erp_bindings", [column])


def downgrade() -> None:
    op.execute("DELETE FROM integration_clients WHERE client_type = 'OPERATOR'")
    op.drop_table("erp_bindings")
    op.drop_table("operator_supplier_cooperations")
    op.drop_table("operator_profiles")
    op.drop_table("operator_applications")
    op.drop_constraint("ck_integration_client_owner", "integration_clients", type_="check")
    op.drop_index("ix_integration_clients_owner_organization_id", table_name="integration_clients")
    op.drop_constraint("fk_integration_clients_owner_organization_id", "integration_clients", type_="foreignkey")
    op.drop_column("integration_clients", "owner_organization_id")
    op.drop_column("integration_clients", "client_type")
