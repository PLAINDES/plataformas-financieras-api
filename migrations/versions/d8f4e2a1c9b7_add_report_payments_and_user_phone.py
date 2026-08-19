"""add report payments and user phone

Revision ID: d8f4e2a1c9b7
Revises: a1b2c3d4e5f6
Create Date: 2026-08-14
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision: str = "d8f4e2a1c9b7"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sys_users",
        sa.Column("phone_number", sa.String(length=30), nullable=True),
    )

    op.create_table(
        "main_report_payments",
        sa.Column(
            "id",
            mysql.BIGINT(unsigned=True),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("external_reference_id", sa.String(length=100), nullable=False),
        sa.Column("report_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("calculation_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("user_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("session_token", sa.String(length=500), nullable=True),
        sa.Column("checkout_url", sa.String(length=1000), nullable=True),
        sa.Column("amount", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column(
            "status",
            sa.String(length=30),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("transaction_id", sa.String(length=255), nullable=True),
        sa.Column("customer_email", sa.String(length=255), nullable=False),
        sa.Column("customer_first_name", sa.String(length=255), nullable=False),
        sa.Column("customer_last_name", sa.String(length=255), nullable=True),
        sa.Column("customer_phone", sa.String(length=30), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("paid_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["calculation_id"], ["main_calculations.id"]),
        sa.ForeignKeyConstraint(["report_id"], ["main_reports.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["sys_users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_main_report_payments_calculation_id"),
        "main_report_payments",
        ["calculation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_main_report_payments_external_reference_id"),
        "main_report_payments",
        ["external_reference_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_main_report_payments_report_id"),
        "main_report_payments",
        ["report_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_main_report_payments_status"),
        "main_report_payments",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_main_report_payments_transaction_id"),
        "main_report_payments",
        ["transaction_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_main_report_payments_user_id"),
        "main_report_payments",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_main_report_payments_user_id"),
        table_name="main_report_payments",
    )
    op.drop_index(
        op.f("ix_main_report_payments_transaction_id"),
        table_name="main_report_payments",
    )
    op.drop_index(
        op.f("ix_main_report_payments_status"),
        table_name="main_report_payments",
    )
    op.drop_index(
        op.f("ix_main_report_payments_report_id"),
        table_name="main_report_payments",
    )
    op.drop_index(
        op.f("ix_main_report_payments_external_reference_id"),
        table_name="main_report_payments",
    )
    op.drop_index(
        op.f("ix_main_report_payments_calculation_id"),
        table_name="main_report_payments",
    )
    op.drop_table("main_report_payments")
    op.drop_column("sys_users", "phone_number")
