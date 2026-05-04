"""Backfill MEGA refresh_token from sid_or_token

Revision ID: 20260504_02
Revises: 20260504_01
Create Date: 2026-05-04 16:50:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260504_02"
down_revision: Union[str, None] = "20260504_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "accounts" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("accounts")}
    required_columns = {"provider", "refresh_token", "sid_or_token"}
    if not required_columns.issubset(columns):
        return

    op.execute(
        sa.text(
            """
            UPDATE accounts
            SET refresh_token = sid_or_token
            WHERE provider = 'mega'
              AND sid_or_token IS NOT NULL
              AND (refresh_token IS NULL OR TRIM(refresh_token) = '')
            """
        )
    )


def downgrade() -> None:
    # This data migration is not safely reversible.
    pass
