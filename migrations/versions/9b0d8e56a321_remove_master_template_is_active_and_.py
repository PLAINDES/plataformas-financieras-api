"""remove_master_template_is_active_and_hojas_config

Revision ID: 9b0d8e56a321
Revises: f7b9c1a2e4d0
Create Date: 2026-04-20 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9b0d8e56a321"
down_revision: Union[str, Sequence[str], None] = "f7b9c1a2e4d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("main_master_templates"):
        return

    existing_columns = {col["name"] for col in inspector.get_columns("main_master_templates")}

    if "is_active" in existing_columns:
        op.drop_column("main_master_templates", "is_active")

    if "hojas_config" in existing_columns:
        op.drop_column("main_master_templates", "hojas_config")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("main_master_templates"):
        return

    existing_columns = {col["name"] for col in inspector.get_columns("main_master_templates")}

    if "is_active" not in existing_columns:
        op.add_column(
            "main_master_templates",
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        )
        op.alter_column("main_master_templates", "is_active", server_default=None)

    if "hojas_config" not in existing_columns:
        op.add_column("main_master_templates", sa.Column("hojas_config", sa.JSON(), nullable=True))
