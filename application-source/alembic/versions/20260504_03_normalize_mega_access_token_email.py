"""Normalize MEGA access_token to account email

Revision ID: 20260504_03
Revises: 20260504_02
Create Date: 2026-05-04 16:58:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260504_03"
down_revision: Union[str, None] = "20260504_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "accounts" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("accounts")}
    required_columns = {"provider", "email", "access_token"}
    if not required_columns.issubset(columns):
        return

    op.execute(
        sa.text(
            """
            UPDATE accounts
            SET access_token = email
            WHERE provider = 'mega'
              AND email IS NOT NULL
              AND TRIM(email) <> ''
              AND (access_token IS NULL OR TRIM(access_token) = '' OR access_token <> email)
            """
        )
    )


def downgrade() -> None:
    # This data normalization is not safely reversible.
    pass
