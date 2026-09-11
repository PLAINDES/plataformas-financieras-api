"""add S3 object key to master templates

Revision ID: b7c8d9e0f1a2
Revises: d8f4e2a1c9b7
Create Date: 2026-09-04 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7c8d9e0f1a2"
down_revision: Union[str, Sequence[str], None] = "d8f4e2a1c9b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("main_master_templates"):
        columns = {column["name"] for column in inspector.get_columns("main_master_templates")}
        if "s3_object_key" not in columns:
            op.add_column(
                "main_master_templates",
                sa.Column("s3_object_key", sa.String(length=1024), nullable=True),
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("main_master_templates"):
        columns = {column["name"] for column in inspector.get_columns("main_master_templates")}
        if "s3_object_key" in columns:
            op.drop_column("main_master_templates", "s3_object_key")
