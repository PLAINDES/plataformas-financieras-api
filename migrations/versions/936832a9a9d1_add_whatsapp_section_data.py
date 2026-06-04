"""add_whatsapp_section_data

Revision ID: 936832a9a9d1
Revises: ec220c2f8350
Create Date: 2026-06-03 22:04:37.216373

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "936832a9a9d1"
down_revision: Union[str, Sequence[str], None] = "ec220c2f8350"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Insertar tipo de contenido para el boton de WhatsApp
    op.execute("""
        INSERT IGNORE INTO `cms_content_types` 
        (`id`, `name`, `label`, `label_plural`, `content_schema`, `icon`, `is_singleton`)
        VALUES (35, 'whatsapp_button', 'WhatsApp Button', 'WhatsApp Buttons', '{"whatsappNumber": "string", "defaultMessage": "string"}', 'message-circle', 1)
    """)

    # Insertar la nueva seccion en la pagina principal
    op.execute("""
        INSERT IGNORE INTO `cms_sections` 
        (`id`, `page_id`, `name`, `component`, `order`, `is_visible`, `created_at`, `updated_at`)
        VALUES (42, 1, 'whatsapp-home', 'WhatsAppSection', 7, 1, NOW(), NOW())
    """)

    # Insertar los datos del contenido
    op.execute("""
        INSERT IGNORE INTO `cms_contents` 
        (`id`, `page_id`, `content_type_id`, `slug`, `admin_label`, `data`, `status`, `is_visible`, `created_at`, `updated_at`)
        VALUES (311, 1, 35, 'whatsapp-home', 'Boton Directo WhatsApp', '{"whatsappNumber": "51999999999", "defaultMessage": "Hola, me gustaria recibir más información."}', 'published', 1, NOW(), NOW())
    """)

    # Insertar la relacion entre la seccion y el contenido
    op.execute("""
        INSERT IGNORE INTO `cms_section_contents` 
        (`id`, `section_id`, `content_id`, `order`, `is_visible`, `created_at`, `updated_at`)
        VALUES (18, 42, 311, 0, 1, NOW(), NOW())
    """)


def downgrade() -> None:
    # Eliminar los registros creados si se revierte la migracion
    op.execute("DELETE FROM `cms_section_contents` WHERE id = 18")
    op.execute("DELETE FROM `cms_contents` WHERE id = 311")
    op.execute("DELETE FROM `cms_sections` WHERE id = 42")
    op.execute("DELETE FROM `cms_content_types` WHERE id = 35")
