"""add s3_object_key to main_calculations

Revision ID: e3f4a5b6c7d8
Revises: d8f4e2a1c9b7
Create Date: 2026-09-08
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e3f4a5b6c7d8"
down_revision: Union[str, Sequence[str], None] = "b7c8d9e0f1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "main_calculations",
        sa.Column("s3_object_key", sa.String(length=1024), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("main_calculations", "s3_object_key")
