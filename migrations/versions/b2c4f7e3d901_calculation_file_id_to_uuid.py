"""calculation_file_id_to_uuid

Revision ID: b2c4f7e3d901
Revises: 9b0d8e56a321
Create Date: 2026-04-21 10:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


# revision identifiers, used by Alembic.
revision: str = "b2c4f7e3d901"
down_revision: Union[str, Sequence[str], None] = "9b0d8e56a321"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("main_calculations"):
        return

    for fk in inspector.get_foreign_keys("main_calculations"):
        if fk.get("constrained_columns") == ["calculation_file_id"] and fk.get("name"):
            op.drop_constraint(fk["name"], "main_calculations", type_="foreignkey")

    op.alter_column(
        "main_calculations",
        "calculation_file_id",
        existing_type=mysql.BIGINT(unsigned=True),
        type_=sa.String(length=36),
        nullable=True,
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("main_calculations"):
        return

    bind.execute(
        sa.text(
            """
            UPDATE main_calculations
            SET calculation_file_id = NULL
            WHERE calculation_file_id IS NOT NULL
              AND calculation_file_id NOT REGEXP '^[0-9]+$'
            """
        )
    )

    op.alter_column(
        "main_calculations",
        "calculation_file_id",
        existing_type=sa.String(length=36),
        type_=mysql.BIGINT(unsigned=True),
        nullable=True,
    )

    op.create_foreign_key(
        "fk_main_calculations_calculation_file_id_cms_media",
        "main_calculations",
        "cms_media",
        ["calculation_file_id"],
        ["id"],
    )
