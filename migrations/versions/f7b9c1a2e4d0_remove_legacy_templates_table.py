"""remove_legacy_templates_table

Revision ID: f7b9c1a2e4d0
Revises: c5f2aa11d2b0
Create Date: 2026-03-26 22:20:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


# revision identifiers, used by Alembic.
revision: str = "f7b9c1a2e4d0"
down_revision: Union[str, Sequence[str], None] = "c5f2aa11d2b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _ensure_default_master_template(bind) -> int:
    default_id = bind.execute(
        sa.text(
            """
            SELECT id
            FROM main_master_templates
            WHERE deleted_at IS NULL AND is_default = 1
            ORDER BY id ASC
            LIMIT 1
            """
        )
    ).scalar()
    if default_id is not None:
        return int(default_id)

    any_id = bind.execute(
        sa.text("SELECT id FROM main_master_templates ORDER BY id ASC LIMIT 1")
    ).scalar()
    if any_id is not None:
        bind.execute(
            sa.text(
                "UPDATE main_master_templates SET is_default = 1 WHERE id = :id"
            ),
            {"id": any_id},
        )
        return int(any_id)

    bind.execute(
        sa.text(
            """
            INSERT INTO main_master_templates (
                nombre,
                description,
                onedrive_env,
                onedrive_folder,
                onedrive_item_id,
                onedrive_filename,
                onedrive_path,
                is_active,
                is_default,
                hojas_config,
                created_by_user_id,
                created_at,
                updated_at,
                deleted_at
            ) VALUES (
                :nombre,
                NULL,
                NULL,
                NULL,
                NULL,
                NULL,
                NULL,
                1,
                1,
                NULL,
                NULL,
                NOW(),
                NOW(),
                NULL
            )
            """
        ),
        {"nombre": "Master Template Migrado"},
    )
    created_id = bind.execute(sa.text("SELECT LAST_INSERT_ID()")).scalar()
    return int(created_id)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("main_master_templates"):
        return

    default_master_id = _ensure_default_master_template(bind)

    if inspector.has_table("main_reports"):
        bind.execute(
            sa.text(
                """
                UPDATE main_reports r
                LEFT JOIN main_master_templates m ON m.id = r.template_id
                SET r.template_id = :default_master_id
                WHERE m.id IS NULL
                """
            ),
            {"default_master_id": default_master_id},
        )

        report_fks = inspector.get_foreign_keys("main_reports")
        fk_to_legacy = next(
            (
                fk.get("name")
                for fk in report_fks
                if fk.get("constrained_columns") == ["template_id"]
                and fk.get("referred_table") == "main_templates"
            ),
            None,
        )
        if fk_to_legacy:
            op.drop_constraint(fk_to_legacy, "main_reports", type_="foreignkey")

        report_fks = inspector.get_foreign_keys("main_reports")
        fk_to_master = next(
            (
                fk.get("name")
                for fk in report_fks
                if fk.get("constrained_columns") == ["template_id"]
                and fk.get("referred_table") == "main_master_templates"
            ),
            None,
        )
        if not fk_to_master:
            op.create_foreign_key(
                "fk_main_reports_template_id_main_master_templates",
                "main_reports",
                "main_master_templates",
                ["template_id"],
                ["id"],
            )

    if inspector.has_table("main_template_codes_main_templates"):
        if inspector.has_table("main_template_codes_master_templates"):
            bind.execute(
                sa.text(
                    """
                    INSERT INTO main_template_codes_master_templates (template_code_id, master_template_id)
                    SELECT DISTINCT
                        old_links.template_code_id,
                        COALESCE(master.id, :default_master_id) AS mapped_master_id
                    FROM main_template_codes_main_templates old_links
                    LEFT JOIN main_master_templates master
                        ON master.id = old_links.template_id
                    LEFT JOIN main_template_codes_master_templates new_links
                        ON new_links.template_code_id = old_links.template_code_id
                        AND new_links.master_template_id = COALESCE(master.id, :default_master_id)
                    WHERE new_links.template_code_id IS NULL
                    """
                ),
                {"default_master_id": default_master_id},
            )

        op.drop_table("main_template_codes_main_templates")

    inspector = sa.inspect(bind)
    if inspector.has_table("main_templates"):
        op.drop_table("main_templates")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("main_templates"):
        op.create_table(
            "main_templates",
            sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
            sa.Column("nombre", sa.String(length=255), nullable=False),
            sa.Column("template_file_id", mysql.BIGINT(unsigned=True), nullable=True),
            sa.Column("is_default", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["template_file_id"], ["cms_media.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    if inspector.has_table("main_master_templates"):
        bind.execute(
            sa.text(
                """
                INSERT INTO main_templates (id, nombre, template_file_id, is_default, created_at, updated_at, deleted_at)
                SELECT mt.id, mt.nombre, NULL, mt.is_default, mt.created_at, mt.updated_at, mt.deleted_at
                FROM main_master_templates mt
                LEFT JOIN main_templates t ON t.id = mt.id
                WHERE t.id IS NULL
                """
            )
        )

    inspector = sa.inspect(bind)
    if inspector.has_table("main_reports"):
        report_fks = inspector.get_foreign_keys("main_reports")
        fk_to_master = next(
            (
                fk.get("name")
                for fk in report_fks
                if fk.get("constrained_columns") == ["template_id"]
                and fk.get("referred_table") == "main_master_templates"
            ),
            None,
        )
        if fk_to_master:
            op.drop_constraint(fk_to_master, "main_reports", type_="foreignkey")

        report_fks = inspector.get_foreign_keys("main_reports")
        fk_to_legacy = next(
            (
                fk.get("name")
                for fk in report_fks
                if fk.get("constrained_columns") == ["template_id"]
                and fk.get("referred_table") == "main_templates"
            ),
            None,
        )
        if not fk_to_legacy:
            op.create_foreign_key(
                "fk_main_reports_template_id_main_templates",
                "main_reports",
                "main_templates",
                ["template_id"],
                ["id"],
            )

    inspector = sa.inspect(bind)
    if not inspector.has_table("main_template_codes_main_templates"):
        op.create_table(
            "main_template_codes_main_templates",
            sa.Column("template_code_id", mysql.BIGINT(unsigned=True), nullable=False),
            sa.Column("template_id", mysql.BIGINT(unsigned=True), nullable=False),
            sa.ForeignKeyConstraint(["template_code_id"], ["main_template_codes.id"]),
            sa.ForeignKeyConstraint(["template_id"], ["main_templates.id"]),
            sa.PrimaryKeyConstraint("template_code_id", "template_id"),
        )

    if inspector.has_table("main_template_codes_master_templates"):
        bind.execute(
            sa.text(
                """
                INSERT INTO main_template_codes_main_templates (template_code_id, template_id)
                SELECT DISTINCT mtcmt.template_code_id, mtcmt.master_template_id
                FROM main_template_codes_master_templates mtcmt
                LEFT JOIN main_template_codes_main_templates legacy
                    ON legacy.template_code_id = mtcmt.template_code_id
                    AND legacy.template_id = mtcmt.master_template_id
                WHERE legacy.template_code_id IS NULL
                """
            )
        )