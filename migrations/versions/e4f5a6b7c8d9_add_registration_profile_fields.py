"""add identity fields required by registration"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e4f5a6b7c8d9"
down_revision: Union[str, Sequence[str], None] = "d9e0f1a2b3c4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sys_users", sa.Column("birth_date", sa.Date(), nullable=True))
    op.add_column("sys_users", sa.Column("document_type", sa.String(length=10), nullable=True))
    op.add_column("sys_users", sa.Column("document_number", sa.String(length=30), nullable=True))
    op.add_column("sys_users", sa.Column("ruc", sa.String(length=20), nullable=True))
    op.create_index("ix_sys_users_document_number", "sys_users", ["document_number"], unique=True)
    op.create_index("ix_sys_users_ruc", "sys_users", ["ruc"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_sys_users_ruc", table_name="sys_users")
    op.drop_index("ix_sys_users_document_number", table_name="sys_users")
    op.drop_column("sys_users", "ruc")
    op.drop_column("sys_users", "document_number")
    op.drop_column("sys_users", "document_type")
    op.drop_column("sys_users", "birth_date")
