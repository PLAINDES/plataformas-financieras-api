"""remove unused utm columns from analytics sessions

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("analytics_sessions", "utm_campaign")
    op.drop_column("analytics_sessions", "utm_medium")


def downgrade() -> None:
    op.add_column("analytics_sessions", sa.Column("utm_medium", sa.String(length=100), nullable=True))
    op.add_column("analytics_sessions", sa.Column("utm_campaign", sa.String(length=100), nullable=True))
