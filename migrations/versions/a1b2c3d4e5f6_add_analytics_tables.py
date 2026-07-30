"""add_analytics_tables

Revision ID: a1b2c3d4e5f6
Revises: f7b9c1a2e4d0
Create Date: 2026-07-29 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "936832a9a9d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "analytics_sessions",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("city", sa.String(length=100), nullable=True),
        sa.Column("country", sa.String(length=100), nullable=True),
        sa.Column("device_type", sa.String(length=20), nullable=True),
        sa.Column("os", sa.String(length=50), nullable=True),
        sa.Column("browser", sa.String(length=50), nullable=True),
        sa.Column("entry_page", sa.String(length=255), nullable=True),
        sa.Column("referrer", sa.String(length=500), nullable=True),
        sa.Column("start_time", sa.DateTime(), nullable=False),
        sa.Column("end_time", sa.DateTime(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["sys_users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_analytics_sessions_session_id"),
        "analytics_sessions",
        ["session_id"],
        unique=True,
    )

    op.create_table(
        "analytics_page_views",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("page_path", sa.String(length=255), nullable=False),
        sa.Column("referrer", sa.String(length=500), nullable=True),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("time_on_page", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["analytics_sessions.session_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_analytics_page_views_session_id"),
        "analytics_page_views",
        ["session_id"],
        unique=False,
    )

    op.create_table(
        "analytics_events",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("event_name", sa.String(length=50), nullable=False),
        sa.Column("page_path", sa.String(length=255), nullable=True),
        sa.Column("event_metadata", sa.JSON(), nullable=True),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["analytics_sessions.session_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_analytics_events_session_id"),
        "analytics_events",
        ["session_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_analytics_events_session_id"), table_name="analytics_events"
    )
    op.drop_table("analytics_events")
    op.drop_index(
        op.f("ix_analytics_page_views_session_id"), table_name="analytics_page_views"
    )
    op.drop_table("analytics_page_views")
    op.drop_index(
        op.f("ix_analytics_sessions_session_id"), table_name="analytics_sessions"
    )
    op.drop_table("analytics_sessions")
