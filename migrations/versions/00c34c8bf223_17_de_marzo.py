"""17 de marzo

Revision ID: 00c34c8bf223
Revises: f8621f909e0c
Create Date: 2026-03-17 14:01:59.422914

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '00c34c8bf223'
down_revision: Union[str, Sequence[str], None] = 'f8621f909e0c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Crear tabla main_master_templates
    op.create_table(
        'main_master_templates',
        sa.Column('id', sa.BigInteger().with_variant(sa.dialects.mysql.BIGINT(unsigned=True), 'mysql'), nullable=False),
        sa.Column('nombre', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('onedrive_env', sa.String(length=20), nullable=True),
        sa.Column('onedrive_folder', sa.String(length=50), nullable=True),
        sa.Column('onedrive_item_id', sa.String(length=512), nullable=True),
        sa.Column('onedrive_filename', sa.String(length=512), nullable=True),
        sa.Column('onedrive_path', sa.String(length=1024), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('hojas_config', sa.JSON(), nullable=True),
        sa.Column('created_by_user_id', sa.BigInteger().with_variant(sa.dialects.mysql.BIGINT(unsigned=True), 'mysql'), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['sys_users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('main_master_templates')

