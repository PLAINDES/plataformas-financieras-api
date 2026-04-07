"""add_default_and_master_codes_link

Revision ID: c5f2aa11d2b0
Revises: ae5c890e945a
Create Date: 2026-03-26 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


# revision identifiers, used by Alembic.
revision: str = "c5f2aa11d2b0"
down_revision: Union[str, Sequence[str], None] = "ae5c890e945a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    existing_columns = {col["name"] for col in inspector.get_columns("main_master_templates")}
    if "is_default" not in existing_columns:
        op.add_column(
            "main_master_templates",
            sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
        op.alter_column("main_master_templates", "is_default", server_default=None)

    if not inspector.has_table("main_template_codes_master_templates"):
        op.create_table(
            "main_template_codes_master_templates",
            sa.Column("template_code_id", mysql.BIGINT(unsigned=True), nullable=False),
            sa.Column("master_template_id", mysql.BIGINT(unsigned=True), nullable=False),
            sa.ForeignKeyConstraint(["template_code_id"], ["main_template_codes.id"]),
            sa.ForeignKeyConstraint(["master_template_id"], ["main_master_templates.id"]),
            sa.PrimaryKeyConstraint("template_code_id", "master_template_id"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("main_template_codes_master_templates"):
        op.drop_table("main_template_codes_master_templates")

    existing_columns = {col["name"] for col in inspector.get_columns("main_master_templates")}
    if "is_default" in existing_columns:
        op.drop_column("main_master_templates", "is_default")
