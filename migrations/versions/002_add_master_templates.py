"""Add main_master_templates table

Revision ID: 002_master_templates
Revises: 001_add_indexes
Create Date: 2026-03-12

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision: str = '002_master_templates'
down_revision: Union[str, Sequence[str], None] = '001_add_indexes'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#pylint: skip-file

def upgrade() -> None:
    op.create_table(
        'main_master_templates',
        sa.Column('id', mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column('nombre', sa.String(length=255), nullable=False),
        sa.Column('version', sa.String(length=50), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('type',
            sa.Enum('valora', 'kapital', name='mastertemplatetype'),
            nullable=False, server_default='valora'),
        sa.Column('onedrive_env', sa.String(length=20), nullable=True),
        sa.Column('onedrive_folder', sa.String(length=50), nullable=True),
        sa.Column('onedrive_item_id', sa.String(length=512), nullable=True),
        sa.Column('onedrive_filename', sa.String(length=512), nullable=True),
        sa.Column('onedrive_path', sa.String(length=1024), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('hojas_config', sa.JSON(), nullable=True),
        sa.Column('created_by_user_id', mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['sys_users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_main_master_templates_deleted_at', 'main_master_templates', ['deleted_at'])
    op.create_index('ix_main_master_templates_type', 'main_master_templates', ['type'])


def downgrade() -> None:
    op.drop_index('ix_main_master_templates_type', table_name='main_master_templates')
    op.drop_index('ix_main_master_templates_deleted_at', table_name='main_master_templates')
    op.drop_table('main_master_templates')
    op.execute("DROP TYPE IF EXISTS mastertemplatetype")
