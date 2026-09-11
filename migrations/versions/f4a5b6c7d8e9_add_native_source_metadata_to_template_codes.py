"""add native source metadata to template codes"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f4a5b6c7d8e9"
down_revision: Union[str, Sequence[str], None] = "e3f4a5b6c7d8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("main_template_codes", sa.Column("source_path", sa.String(255), nullable=True))
    op.add_column("main_template_codes", sa.Column("source_format", sa.String(32), nullable=True))


def downgrade() -> None:
    op.drop_column("main_template_codes", "source_format")
    op.drop_column("main_template_codes", "source_path")
