"""Add indexes for TemplateComplement to improve query performance

Revision ID: 001_add_indexes
Revises: 2749c740c21c
Create Date: 2026-03-12 12:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

#pylint: skip-file

# revision identifiers, used by Alembic.
revision: str = '001_add_indexes'
down_revision: Union[str, Sequence[str], None] = '2749c740c21c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add indexes to main_template_complements table."""
    
    # Add index on created_at for sorting
    op.create_index(
        op.f('ix_main_template_complements_created_at'),
        'main_template_complements',
        ['created_at'],
        unique=False
    )
    
    # Add index on (deleted_at, id) for filtered queries and max ID lookups
    op.create_index(
        op.f('ix_main_template_complements_deleted_id'),
        'main_template_complements',
        ['deleted_at', 'id'],
        unique=False
    )


def downgrade() -> None:
    """Remove indexes."""
    op.drop_index(
        op.f('ix_main_template_complements_deleted_id'),
        table_name='main_template_complements'
    )
    op.drop_index(
        op.f('ix_main_template_complements_created_at'),
        table_name='main_template_complements'
    )
