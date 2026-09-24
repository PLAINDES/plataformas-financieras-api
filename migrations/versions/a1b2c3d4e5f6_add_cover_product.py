"""add product to covers

Revision ID: a1b2c3d4e5f6
Revises: f7b9c1a2e4d0
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, Sequence[str], None] = "e4f5a6b7c8d9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("main_covers", sa.Column("producto", sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column("main_covers", "producto")
