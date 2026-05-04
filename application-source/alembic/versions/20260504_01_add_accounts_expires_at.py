"""Add accounts.expires_at column

Revision ID: 20260504_01
Revises:
Create Date: 2026-05-04 16:15:00
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260504_01"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add expires_at column to accounts table."""

    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "accounts" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("accounts")}
    if "expires_at" not in columns:
        op.add_column("accounts", sa.Column("expires_at", sa.Integer(), nullable=True))


def downgrade() -> None:
    """Remove expires_at column from accounts table."""

    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "accounts" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("accounts")}
    if "expires_at" in columns:
        op.drop_column("accounts", "expires_at")
