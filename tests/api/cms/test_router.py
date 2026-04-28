# tests/api/cms/test_router.py
"""
Módulo de Pruebas para el CMS.

Este módulo contiene pruebas para:
1. Validar la integridad de los datos semilla (seeds) insertados en la base de datos temporal.
2. Comprobar el correcto funcionamiento de los endpoints públicos y privados del CMS.
3. Verificar la persistencia de datos y la creación de registros de auditoría al actualizar contenidos.
4. Asegurar que las operaciones de escritura directa en BD funcionan y se pueden revertir limpiamente.
"""
import hashlib
import json

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.cms import Auditory, Content, ContentStatus

PREFIX = "/api/v1/cms"


def test_seed_basic_data_integrity(db_session: Session):
    """
    Verifica que las tablas principales del CMS (pages, content_types, section_contents)
    contengan los datos básicos iniciales tras la ejecución de los seeds.
    """
    page = db_session.execute(
        text("""
        SELECT id, slug, title, is_homepage, status
        FROM cms_pages
        WHERE id = 1
        """)
    ).mappings().first()

    assert page is not None
    assert page["slug"] == "home"
    assert page["title"] == "Inicio"
    assert page["is_homepage"] == 1
    assert page["status"] == "published"

    content_types = db_session.execute(
        text("SELECT COUNT(*) AS total FROM cms_content_types")
    ).mappings().first()
    assert content_types["total"] >= 10

    section_content = db_session.execute(
        text("""
        SELECT sc.section_id, c.id AS content_id, c.slug
        FROM cms_section_contents sc
        INNER JOIN cms_contents c ON c.id = sc.content_id
        WHERE sc.section_id = 1
        """)
    ).mappings().all()

    assert len(section_content) > 0
    assert any(row["slug"] == "hero-home" for row in section_content)


def test_seed_cms_pages_exact_values(db_session: Session):
    """
    Valida que la configuración JSON (settings) y los campos SEO
    de la página de inicio (ID 1) coincidan exactamente con lo esperado.
    """
    row = db_session.execute(
        text("""
        SELECT settings, seo_title, seo_description
        FROM cms_pages
        WHERE id = 1
        """)
    ).mappings().first()

    assert row is not None

    settings = row["settings"]
    if isinstance(settings, str):
        settings = json.loads(settings)

    assert settings == {
        "layout": "full",
        "show_footer": True,
        "show_header": True,
    }
    assert row["seo_title"] == "Plataforma Finanzas | Inicio"
    assert row["seo_description"] == "Plataforma Finanzas - Soluciones financieras modernas"


def test_seed_cms_sections_exact_values(db_session: Session):
    """
    Verifica los valores exactos, incluyendo orden y componentes asociados,
    de las primeras secciones (hero y cta) inyectadas por los seeds.
    """
    rows = db_session.execute(
        text("""
        SELECT
            id,
            page_id,
            name,
            component,
            `order`,
            is_visible,
            DATE_FORMAT(created_at, '%Y-%m-%d %H:%i:%s') AS created_at,
            DATE_FORMAT(updated_at, '%Y-%m-%d %H:%i:%s') AS updated_at,
            deleted_at
        FROM cms_sections
        WHERE id IN (1, 2)
        ORDER BY id ASC
        """)
    ).mappings().all()

    assert len(rows) == 2

    assert dict(rows[0]) == {
        "id": 1,
        "page_id": 1,
        "name": "hero-home",
        "component": "HeroSection",
        "order": 1,
        "is_visible": 1,
        "created_at": "2026-01-29 10:54:57",
        "updated_at": "2026-01-29 10:54:57",
        "deleted_at": None,
    }

    assert dict(rows[1]) == {
        "id": 2,
        "page_id": 1,
        "name": "cta-home",
        "component": "CTASection",
        "order": 3,
        "is_visible": 1,
        "created_at": "2026-01-29 10:55:03",
        "updated_at": "2026-01-29 10:55:03",
        "deleted_at": None,
    }


def test_seed_calculation_data_integrity(db_session: Session):
    """
    Comprueba que el lote de datos analíticos y financieros (media, cálculos,
    portadas y plantillas) se haya insertado correctamente.
    """
    media_rows = db_session.execute(
        text("SELECT COUNT(*) AS total FROM cms_media WHERE id IN (30, 31, 32, 33, 34)")
    ).mappings().first()
    assert media_rows["total"] == 5

    valora_rows = db_session.execute(
        text("SELECT COUNT(*) AS total FROM main_calculations WHERE id IN (101, 102, 103) AND type = 'valora'")
    ).mappings().first()
    assert valora_rows["total"] == 3

    kapital_rows = db_session.execute(
        text("SELECT COUNT(*) AS total FROM main_calculations WHERE id IN (201, 202, 203, 204) AND type = 'kapital'")
    ).mappings().first()
    assert kapital_rows["total"] == 4

    cover_row = db_session.execute(
        text("SELECT id FROM main_covers WHERE id = 10")
    ).mappings().first()
    assert cover_row is not None

    template_row = db_session.execute(
        text("SELECT id FROM main_master_templates WHERE id = 10")
    ).mappings().first()
    assert template_row is not None


def test_seed_main_calculations_exact_row_101(db_session: Session):
    """
    Verifica la correcta extracción de atributos desde un campo JSON y la
    generación del código SHA256 para un registro específico de cálculo.
    """
    row = db_session.execute(
        text("""
        SELECT
            id,
            calculation_file_id,
            user_id,
            code,
            type,
            JSON_UNQUOTE(JSON_EXTRACT(data, '$.pais')) AS pais,
            JSON_UNQUOTE(JSON_EXTRACT(data, '$.moneda')) AS moneda,
            JSON_UNQUOTE(JSON_EXTRACT(data, '$.sector')) AS sector,
            JSON_UNQUOTE(JSON_EXTRACT(data, '$.fecha')) AS fecha,
            JSON_UNQUOTE(JSON_EXTRACT(data, '$.archivo')) AS archivo,
            JSON_UNQUOTE(JSON_EXTRACT(data, '$.media_id')) AS media_id,
            DATE_FORMAT(created_at, '%Y-%m-%d %H:%i:%s') AS created_at,
            DATE_FORMAT(updated_at, '%Y-%m-%d %H:%i:%s') AS updated_at
        FROM main_calculations
        WHERE id = 101
        """)
    ).mappings().first()

    assert row is not None
    assert row["id"] == 101
    assert int(row["calculation_file_id"]) == 30
    assert row["user_id"] == 15
    assert row["type"] == "valora"
    assert row["pais"] == "Chile"
    assert row["moneda"] == "CLP"
    assert row["sector"] == "Tecnologia" or row["sector"] == "Tecnología"
    assert row["fecha"] == "2026-03-10"
    assert row["archivo"] == "EEFF_Chile_Tecnologia.xlsx"
    assert row["media_id"] == "3"
    assert row["created_at"] == "2026-03-10 10:09:36"
    assert row["updated_at"] == "2026-03-10 10:09:36"

    expected_code = hashlib.sha256("valora-chile-tecnologia-15-2026-03-10".encode("utf-8")).hexdigest()
    assert row["code"] == expected_code


# ===========================================
# TESTS DE ENDPOINTS (API HTTP)
# ===========================================

def test_get_landing_page_success_seeded(client: TestClient):
    """
    Prueba el endpoint principal de la Landing Page sin proporcionar slug.
    Debe retornar la configuración y contenidos de la página definida como 'homepage'.
    """
    response = client.get(f"{PREFIX}/landing")
    assert response.status_code == 200

    payload = response.json()
    assert payload["page"]["id"] == 1
    assert payload["page"]["slug"] == "home"
    assert payload["page"]["title"] == "Inicio"
    assert payload["page"]["is_homepage"] is True
    assert len(payload["page"]["contents"]) > 0
    assert payload["site"]["site_key"] == "main"


def test_get_landing_page_with_slug_seeded(client: TestClient):
    """
    Prueba la consulta de una Landing Page proporcionando explícitamente su slug.
    """
    response = client.get(f"{PREFIX}/landing?slug=home")
    assert response.status_code == 200
    assert response.json()["page"]["slug"] == "home"


def test_get_landing_page_not_found(client: TestClient):
    """
    Valida el manejo de errores al solicitar una página que no existe en BD.
    """
    response = client.get(f"{PREFIX}/landing?slug=pagina-fantasma")
    assert response.status_code == 404


def test_get_section_contents_success_seeded(client: TestClient):
    """
    Prueba el endpoint de lectura de contenidos asociados a una sección específica
    para su edición en el panel de administrador.
    """
    response = client.get(f"{PREFIX}/sections/1/contents")

    assert response.status_code == 200
    payload = response.json()
    assert payload["section"]["id"] == 1
    assert payload["section"]["name"] == "hero-home"
    assert len(payload["contents"]) > 0
    assert payload["contents"][0]["content"]["slug"] == "hero-home"


def test_update_seed_content_success_and_persists(client: TestClient, db_session: Session):
    """
    Prueba el flujo completo de actualización de contenido vía API:
    1. Ejecuta la mutación.
    2. Valida la persistencia en la base de datos real.
    3. Verifica que se haya generado el registro de auditoría correspondiente.
    4. Restaura los datos originales (Clean-up).
    """
    content = db_session.query(Content).filter(Content.id == 1).one()
    previous_data = dict(content.data)
    previous_status = content.status

    payload = {
        "data": {
            **previous_data,
            "title": "Título actualizado desde test de integración"
        },
        "status": "published"
    }

    response = client.put(f"{PREFIX}/contents/{content.id}?author_id=1", json=payload)
    assert response.status_code == 200

    db_session.refresh(content)
    assert content.data["title"] == "Título actualizado desde test de integración"
    assert content.status == ContentStatus.PUBLISHED

    created_log = (
        db_session.query(Auditory)
        .filter(Auditory.content_id == content.id)
        .order_by(Auditory.id.desc())
        .first()
    )
    assert created_log is not None
    assert created_log.author_id == 1
    assert "Contenido Actualizado" in created_log.title
    assert created_log.data["title"] == "Título actualizado desde test de integración"

    # Restauramos la data semilla para no contaminar ejecuciones locales repetidas.
    content.data = previous_data
    content.status = previous_status
    db_session.commit()


def test_update_basic_data_page_and_restore(db_session: Session):
    """
    Prueba la capacidad de actualización directa por SQL y valida el mecanismo
    de restauración para mantener el entorno estable.
    """
    original = db_session.execute(
        text("SELECT seo_title FROM cms_pages WHERE id = 1")
    ).mappings().first()
    assert original is not None

    original_title = original["seo_title"]
    new_title = "Plataforma Finanzas | Inicio QA"

    db_session.execute(
        text("UPDATE cms_pages SET seo_title = :new_title WHERE id = 1"),
        {"new_title": new_title},
    )
    db_session.commit()

    updated = db_session.execute(
        text("SELECT seo_title FROM cms_pages WHERE id = 1")
    ).mappings().first()
    assert updated["seo_title"] == new_title

    db_session.execute(
        text("UPDATE cms_pages SET seo_title = :old_title WHERE id = 1"),
        {"old_title": original_title},
    )
    db_session.commit()


def test_update_calculation_data_and_restore(db_session: Session):
    """
    Prueba la capacidad de realizar modificaciones directas en campos de tipo JSON (JSON_SET)
    y valida el mecanismo de restauración del valor original.
    """
    original = db_session.execute(
        text("""
        SELECT JSON_UNQUOTE(JSON_EXTRACT(data, '$.sector')) AS sector
        FROM main_calculations
        WHERE id = 101
        """)
    ).mappings().first()
    assert original is not None

    original_sector = original["sector"]
    new_sector = "Tecnologia QA"

    db_session.execute(
        text("""
        UPDATE main_calculations
        SET data = JSON_SET(data, '$.sector', :new_sector)
        WHERE id = 101
        """),
        {"new_sector": new_sector},
    )
    db_session.commit()

    updated = db_session.execute(
        text("""
        SELECT JSON_UNQUOTE(JSON_EXTRACT(data, '$.sector')) AS sector
        FROM main_calculations
        WHERE id = 101
        """)
    ).mappings().first()
    assert updated["sector"] == new_sector

    db_session.execute(
        text("""
        UPDATE main_calculations
        SET data = JSON_SET(data, '$.sector', :original_sector)
        WHERE id = 101
        """),
        {"original_sector": original_sector},
    )
    db_session.commit()


def test_get_content_history_success(client: TestClient, db_session: Session):
    """
    Valida la recuperación del historial de auditoría de un contenido específico
    tras insertar manualmente un registro de prueba.
    """
    content = db_session.query(Content).filter(Content.id == 1).one()

    new_log = Auditory(
        content_id=content.id,
        title="Actualización de prueba seed",
        data={"title": "snapshot-history"},
        author_id=1
    )
    db_session.add(new_log)
    db_session.commit()

    response = client.get(f"{PREFIX}/contents/{content.id}/history")

    assert response.status_code == 200
    data = response.json()
    assert len(data) > 0
    assert any(item["title"] == "Actualización de prueba seed" for item in data)
