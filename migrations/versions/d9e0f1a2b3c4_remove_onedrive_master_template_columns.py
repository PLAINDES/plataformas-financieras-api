"""remove legacy OneDrive columns from master templates"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d9e0f1a2b3c4"
down_revision: Union[str, Sequence[str], None] = "c7d8e9f0a1b2"
branch_labels = None
depends_on = None


_COLUMNS = (
    ("onedrive_env", sa.String(length=20)),
    ("onedrive_folder", sa.String(length=50)),
    ("onedrive_item_id", sa.String(length=512)),
    ("onedrive_filename", sa.String(length=512)),
    ("onedrive_path", sa.String(length=1024)),
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table = "main_master_templates"
    if not inspector.has_table(table):
        return

    columns = {column["name"] for column in inspector.get_columns(table)}
    for name, _ in _COLUMNS:
        if name in columns:
            op.drop_column(table, name)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table = "main_master_templates"
    if not inspector.has_table(table):
        return

    columns = {column["name"] for column in inspector.get_columns(table)}
    for name, column_type in _COLUMNS:
        if name not in columns:
            op.add_column(table, sa.Column(name, column_type, nullable=True))
