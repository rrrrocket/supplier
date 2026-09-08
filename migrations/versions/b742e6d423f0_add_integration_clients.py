"""add integration clients

Revision ID: b742e6d423f0
Revises: 5d91a2c74e30
Create Date: 2026-09-09 12:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "b742e6d423f0"
down_revision: Union[str, Sequence[str], None] = "5d91a2c74e30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "integration_clients",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("token_prefix", sa.String(length=24), nullable=False),
        sa.Column("token_hash", sa.String(length=255), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_integration_clients_token_prefix",
        "integration_clients",
        ["token_prefix"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_integration_clients_token_prefix",
        table_name="integration_clients",
    )
    op.drop_table("integration_clients")
