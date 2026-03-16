"""initial

Revision ID: f8621f909e0c
Revises: 
Create Date: 2026-03-15 15:05:38.954438

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision: str = "f8621f909e0c"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    """Upgrade schema."""

    # ─────────────────────────────────────────
    # SYS tables
    # ─────────────────────────────────────────
    op.create_table(
        "sys_users",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("lastname", sa.String(length=255), nullable=True),
        sa.Column(
            "role",
            sa.Enum("master", "admin", "user", name="userrole"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("avatar", sa.String(length=255), nullable=True),
        sa.Column(
            "settings",
            sa.JSON(),
            nullable=True,
            comment="Preferencias de usuario",
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_sys_users_email"), "sys_users", ["email"], unique=True)

    op.create_table(
        "sys_sessions",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("user_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("token", sa.String(length=500), nullable=False),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_sys_sessions_token"), "sys_sessions", ["token"], unique=False)
    op.create_index(op.f("ix_sys_sessions_user_id"), "sys_sessions", ["user_id"], unique=False)

    # ─────────────────────────────────────────
    # CMS tables (sin dependencias externas primero)
    # ─────────────────────────────────────────
    op.create_table(
        "cms_contact_messages",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("subject", sa.String(length=255), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("UNREAD", "READ", "REPLIED", name="messagestatus"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_cms_contact_messages_created_at"),
        "cms_contact_messages",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_cms_contact_messages_status"),
        "cms_contact_messages",
        ["status"],
        unique=False,
    )

    op.create_table(
        "cms_content_types",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("label_plural", sa.String(length=255), nullable=True),
        sa.Column("content_schema", sa.JSON(), nullable=True),
        sa.Column("icon", sa.String(length=50), nullable=True),
        sa.Column("is_singleton", sa.Boolean(), nullable=True),
        sa.Column("settings", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    op.create_table(
        "cms_pages",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("template", sa.String(length=100), nullable=True, comment="Template a usar"),
        sa.Column("parent_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column(
            "status",
            sa.Enum("draft", "published", name="pagestatus"),
            nullable=False,
        ),
        sa.Column("order", sa.Integer(), nullable=True),
        sa.Column("is_homepage", sa.Boolean(), nullable=True),
        sa.Column(
            "settings",
            sa.JSON(),
            nullable=True,
            comment="Configuración de página",
        ),
        sa.Column("seo_title", sa.String(length=255), nullable=True),
        sa.Column("seo_description", sa.Text(), nullable=True),
        sa.Column("seo_image", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["parent_id"], ["cms_pages.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_cms_pages_slug"), "cms_pages", ["slug"], unique=True)

    op.create_table(
        "cms_media",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("original_name", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column(
            "size",
            mysql.BIGINT(unsigned=True),
            nullable=True,
            comment="Tamaño en bytes",
        ),
        sa.Column("url", sa.String(length=500), nullable=False),
        sa.Column("storage_path", sa.String(length=500), nullable=False),
        sa.Column("alt_text", sa.String(length=255), nullable=True),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column(
            "folder",
            sa.String(length=255),
            nullable=True,
            comment="Organización en carpetas",
        ),
        sa.Column("uploaded_by", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column(
            "meta",
            sa.JSON(),
            nullable=True,
            comment="Dimensiones, duración, etc",
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["uploaded_by"], ["sys_users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_cms_media_mime_type"), "cms_media", ["mime_type"], unique=False)

    op.create_table(
        "cms_contents",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("page_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("content_type_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("admin_label", sa.String(length=255), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("draft", "published", "archived", name="contentstatus"),
            nullable=True,
        ),
        sa.Column("is_visible", sa.Boolean(), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("author_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["author_id"], ["sys_users.id"]),
        sa.ForeignKeyConstraint(["content_type_id"], ["cms_content_types.id"]),
        sa.ForeignKeyConstraint(["page_id"], ["cms_pages.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "cms_sections",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("page_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "component",
            sa.String(length=100),
            nullable=False,
            comment="Componente React a renderizar",
        ),
        sa.Column("order", sa.Integer(), nullable=True),
        sa.Column("is_visible", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["page_id"], ["cms_pages.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "cms_auditory_logs",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("content_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("author_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("is_visible", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["author_id"], ["sys_users.id"]),
        sa.ForeignKeyConstraint(["content_id"], ["cms_contents.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "cms_section_contents",
        sa.Column("id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("section_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("content_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("order", sa.Integer(), nullable=True),
        sa.Column("is_visible", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["content_id"], ["cms_contents.id"]),
        sa.ForeignKeyConstraint(["section_id"], ["cms_sections.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "cms_site_settings",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("site_key", sa.String(length=50), nullable=False),
        sa.Column("header_logo_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("header_logo_sticky_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("favicon_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["header_logo_id"], ["cms_media.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # ─────────────────────────────────────────
    # MAIN tables  (versión final de f8621f909e0c)
    # ─────────────────────────────────────────

    # main_template_complements  (sin FKs, puede ir primero)
    op.create_table(
        "main_template_complements",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("nombre", sa.String(length=255), nullable=False),
        sa.Column("fecha", sa.DateTime(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    # main_covers  (FK → cms_media)
    op.create_table(
        "main_covers",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("nombre", sa.String(length=255), nullable=False),
        sa.Column(
            "tipo",
            sa.Enum("imagen_adjuntada", "personalizada", name="covertype"),
            nullable=False,
        ),
        sa.Column("portada_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("primer_imagen_footer_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("segundo_imagen_footer_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("logo_superior_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("imagen_central_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("logo_inferior_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("imagen_fondo_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["imagen_central_id"], ["cms_media.id"]),
        sa.ForeignKeyConstraint(["imagen_fondo_id"], ["cms_media.id"]),
        sa.ForeignKeyConstraint(["logo_inferior_id"], ["cms_media.id"]),
        sa.ForeignKeyConstraint(["logo_superior_id"], ["cms_media.id"]),
        sa.ForeignKeyConstraint(["portada_id"], ["cms_media.id"]),
        sa.ForeignKeyConstraint(["primer_imagen_footer_id"], ["cms_media.id"]),
        sa.ForeignKeyConstraint(["segundo_imagen_footer_id"], ["cms_media.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # main_template_codes  (FK → cms_media)
    op.create_table(
        "main_template_codes",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("template_code_image_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column(
            "type",
            sa.Enum("valora", "kapital", name="templatecodetype"),
            nullable=False,
        ),
        sa.Column("hoja", sa.String(length=255), nullable=True),
        sa.Column("nombre", sa.String(length=255), nullable=False),
        sa.Column("code", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["template_code_image_id"], ["cms_media.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # main_templates  (FK → cms_media)
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

    # main_calculations  (versión final: agrega columna `code` con UniqueConstraint)
    op.create_table(
        "main_calculations",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("calculation_file_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("user_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column(
            "type",
            sa.Enum("valora", "kapital", name="calculationtype"),
            nullable=False,
        ),
        sa.Column("data", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["calculation_file_id"], ["cms_media.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["sys_users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )

    # main_reports  (FK → main_templates, main_covers)
    op.create_table(
        "main_reports",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("template_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("nombre", sa.String(length=255), nullable=False),
        sa.Column("precio", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("moneda", sa.String(length=10), nullable=True),
        sa.Column("sector_empresa", sa.String(length=50), nullable=True),
        sa.Column("bono_ajustado", sa.String(length=50), nullable=True),
        sa.Column("link_pago", sa.String(length=555), nullable=True),
        sa.Column("contenido", sa.String(length=255), nullable=True),
        sa.Column("portada_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("activo", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["portada_id"], ["main_covers.id"]),
        sa.ForeignKeyConstraint(["template_id"], ["main_templates.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # main_template_codes_main_templates  (tabla pivot)
    op.create_table(
        "main_template_codes_main_templates",
        sa.Column("template_code_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("template_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.ForeignKeyConstraint(["template_code_id"], ["main_template_codes.id"]),
        sa.ForeignKeyConstraint(["template_id"], ["main_templates.id"]),
        sa.PrimaryKeyConstraint("template_code_id", "template_id"),
    )


def downgrade() -> None:
    """Downgrade schema."""

    # MAIN tables (orden inverso de dependencias)
    op.drop_table("main_template_codes_main_templates")
    op.drop_table("main_reports")
    op.drop_table("main_calculations")
    op.drop_table("main_templates")
    op.drop_table("main_template_codes")
    op.drop_table("main_covers")
    op.drop_table("main_template_complements")

    # CMS tables
    op.drop_table("cms_site_settings")
    op.drop_table("cms_section_contents")
    op.drop_table("cms_auditory_logs")
    op.drop_table("cms_sections")
    op.drop_table("cms_contents")
    op.drop_index(op.f("ix_cms_media_mime_type"), table_name="cms_media")
    op.drop_table("cms_media")
    op.drop_index(op.f("ix_cms_pages_slug"), table_name="cms_pages")
    op.drop_table("cms_pages")
    op.drop_table("cms_content_types")
    op.drop_index(
        op.f("ix_cms_contact_messages_status"), table_name="cms_contact_messages"
    )
    op.drop_index(
        op.f("ix_cms_contact_messages_created_at"), table_name="cms_contact_messages"
    )
    op.drop_table("cms_contact_messages")

    # SYS tables
    op.drop_index(op.f("ix_sys_sessions_user_id"), table_name="sys_sessions")
    op.drop_index(op.f("ix_sys_sessions_token"), table_name="sys_sessions")
    op.drop_table("sys_sessions")
    op.drop_index(op.f("ix_sys_users_email"), table_name="sys_users")
    op.drop_table("sys_users")