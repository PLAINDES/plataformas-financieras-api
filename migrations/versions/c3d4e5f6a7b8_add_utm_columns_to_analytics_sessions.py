"""add utm columns to analytics sessions

Revision ID: c3d4e5f6a7b8
Revises: b1c2d3e4f5a6
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("analytics_sessions", sa.Column("utm_source", sa.String(length=100), nullable=True))
    op.add_column("analytics_sessions", sa.Column("utm_medium", sa.String(length=100), nullable=True))
    op.add_column("analytics_sessions", sa.Column("utm_campaign", sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column("analytics_sessions", "utm_campaign")
    op.drop_column("analytics_sessions", "utm_medium")
    op.drop_column("analytics_sessions", "utm_source")
