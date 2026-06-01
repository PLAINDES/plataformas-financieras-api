import asyncio
import io
import base64
import logging
import re
from pathlib import Path
from typing import Optional
from urllib.parse import quote
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

import httpx
from starlette import responses

from app.db.database import get_db
from app.api.deps import get_current_admin
from app.models.templates import MasterTemplate
from app.models.main import TemplateCode, CalculationType
from app.models.cms import Media
from app.services.template_code_extractor import normalize_code
from app.services.aws_service import s3_service
from app.core.constants import TEMPLATE_SHEET_TO_TYPE

logger = logging.getLogger(__name__)


# === UTILIDADES GENERALES =====================================================

class SimpleUploadFile:
    """Simula el objeto UploadFile de FastAPI para el s3_service."""
    def __init__(self, filename: str, file_bytes: io.BytesIO):
        self.filename = filename
        self.file = file_bytes
        self.content_type = "image/png"


def _normalize_template_name(template_name: str) -> str:
    normalized = (template_name or "TEMPLATE").upper()
    normalized = re.sub(r"\s+", "_", normalized)
    normalized = re.sub(r"[^A-Z0-9_]", "", normalized)
    normalized = re.sub(r"_+", "_", normalized)
    return normalized.strip("_") or "TEMPLATE"


def _chart_candidate_dirs() -> list[Path]:
    return [
        Path("/app/public/master-templates-graphs"),
        Path("/app/public/chart-images"),
        Path("./public/master-templates-graphs"),
        Path("./public/chart-images"),
    ]

async def _upload_to_s3_async(prefixed_filename, image_bytes, dynamic_folder):
    """Función de ayuda para ejecutar s3_service.upload_file en un hilo."""
    def _upload():
        upload_file = SimpleUploadFile(prefixed_filename, io.BytesIO(image_bytes))
        return s3_service.upload_file(upload_file, folder=dynamic_folder)
    return await asyncio.to_thread(_upload)

def _link_code_to_master_template(master_template: MasterTemplate, code: TemplateCode) -> None:
    if code not in master_template.template_codes:
        master_template.template_codes.append(code)


def _resolve_media_fields(
    template_id: int, prefixed_stem: str, prefixed_filename: str, file_url: Optional[str], object_key: Optional[str],
) -> tuple[str, str]:
    fallback_url = f"/api/v1/main/master-templates/chart-file/{prefixed_stem}"
    fallback_storage_path = object_key or f"master-templates/{template_id}/{prefixed_filename}"
    return (file_url or fallback_url, fallback_storage_path)


def _clear_user_default_templates(db: Session, user_id: int, exclude_template_id: Optional[int] = None) -> None:
    query = select(MasterTemplate).where(
        (MasterTemplate.deleted_at.is_(None))
        & (MasterTemplate.created_by_user_id == user_id)
        & (MasterTemplate.is_default.is_(True))
    )
    if exclude_template_id is not None:
        query = query.where(MasterTemplate.id != exclude_template_id)

    rows = db.execute(query).scalars().all()
    for row in rows:
        row.is_default = False


def _ensure_user_has_default_template(db: Session, user_id: Optional[int]) -> None:
    if not user_id:
        return
    active_templates = db.execute(
        select(MasterTemplate).where(
            (MasterTemplate.deleted_at.is_(None)) & (MasterTemplate.created_by_user_id == user_id)
        ).order_by(MasterTemplate.created_at.desc())
    ).scalars().all()

    if not active_templates or any(t.is_default for t in active_templates):
        return
    active_templates[0].is_default = True


def _process_and_save_cell_codes(db: Session, obj: MasterTemplate, extraction_result: dict, old_code_sets: dict = None) -> tuple[dict, dict]:
    """
    Helper unificado para guardar los TemplateCodes extraídos de celdas.
    Retorna (created_codes, new_codes_only) para las lógicas de upload y re-upload.
    """
    created_codes = {"valora": [], "kapital": []}
    new_codes_only = {"valora": [], "kapital": []}
    old_sets = old_code_sets or {"valora": set(), "kapital": set()}

    for template_type in ["valora", "kapital"]:
        code_enum = CalculationType(template_type)
        for data in extraction_result.get(template_type, []):
            if not data.get("code"):
                continue

            cn = f"$${str(data['code']).replace('$$', '').upper()}$$"
            existing = db.execute(
                select(TemplateCode).where((TemplateCode.code == cn) & (TemplateCode.type == code_enum))
            ).scalars().first()

            if existing:
                existing.deleted_at = None
                existing.nombre = data.get("nombre", "Sin nombre")
                existing.hoja = data.get("hoja")
                existing.value = data.get("value")
                if data.get("coordinate"):
                    existing.coordinate = data.get("coordinate")
                tc = existing
            else:
                tc = TemplateCode(code=cn, nombre=data.get("nombre", "Sin nombre"), type=code_enum, hoja=data.get("hoja"), value=data.get("value"), coordinate=data.get("coordinate"))
                db.add(tc)

            _link_code_to_master_template(obj, tc)
            db.commit()
            db.refresh(tc)

            code_resp = {"id": tc.id, "code": tc.code, "nombre": tc.nombre, "hoja": tc.hoja, "type": template_type, "value": tc.value, "coordinate": tc.coordinate}
            created_codes[template_type].append(code_resp)

            if cn not in old_sets.get(template_type, set()):
                new_codes_only[template_type].append(cn)

    return created_codes, new_codes_only


# === HELPER NATIVO PARA GRÁFICOS (GRAPH API) ==================================

async def _extract_and_save_charts_via_graph(db: Session, template_id: int, obj: MasterTemplate, service):
    """
    1. Llama a Graph API para extraer los gráficos de Excel Online.
    2. Sube a AWS S3.
    3. Guarda los registros en BD (Media y TemplateCode).
    """
    extracted_charts = {"valora": [], "kapital": []}
    errors = []
    total_charts = 0

    token = await service._get_token()
    base_url = f"https://graph.microsoft.com/v1.0/users/{service.config.user_email}/drive/items/{obj.onedrive_item_id}/workbook"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    target_sheets = TEMPLATE_SHEET_TO_TYPE
    template_prefix = _normalize_template_name(obj.nombre)

    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            # 1. Crear sesión de trabajo en Excel Online (RAM)
            session_resp = await client.post(f"{base_url}/createSession", headers=headers, json={"persistChanges": False})
            session_resp.raise_for_status()
            headers["workbook-session-id"] = session_resp.json()["id"]

            download_tasks_meta = [] # Para saber qué gráfico es cada uno
            batch_requests = []
            req_id = 1

            for sheet_name, template_type in target_sheets.items():
                encoded_sheet = quote(sheet_name)
                charts_url = f"{base_url}/worksheets('{encoded_sheet}')/charts"
                charts_resp = await client.get(charts_url, headers=headers)

                if charts_resp.status_code != 200:
                    errors.append(f"No se pudo acceder a la hoja '{sheet_name}'")
                    continue

                for chart in charts_resp.json().get("value", []):
                    chart_title = chart.get("name")
                    if not chart_title:
                        continue
                    #total_charts += 1
                    encoded_chart = quote(chart_title)

                    relative_url = f"/users/{service.config.user_email}/drive/items/{obj.onedrive_item_id}/workbook/worksheets('{encoded_sheet}')/charts('{encoded_chart}')/image"

                    batch_requests.append({
                        "id": str(req_id),
                        "method": "GET",
                        "url": relative_url,
                        "headers": {"workbook-session-id": headers["workbook-session-id"]}
                    })

                    download_tasks_meta.append({
                        "id": str(req_id),
                        "title": chart_title,
                        "type": template_type,
                        "sheet": sheet_name,
                    })
                    req_id += 1

            total_charts = len(batch_requests)

            # 2. EJECUTAR DESCARGAS CONCURRENTES
            responses_map = {}
            if batch_requests:
                chunks = []
                for i in range(0, len(batch_requests), 20):
                    chunks.append(batch_requests[i:i + 20])

                # Ejecutamos los lotes concurrentemente, empaquetados
                batch_tasks = [service.execute_batch(chunk) for chunk in chunks]
                batch_results_list = await asyncio.gather(*batch_tasks, return_exceptions=True)

                # Desempaquetar los resultados en un diccionario { "req_id": response_body }
                for batch_res in batch_results_list:
                    if isinstance(batch_res, Exception):
                        continue
                    for single_response in batch_res:
                        # single_response tiene el formato {"id": "1", "status": 200, "body": {...}}
                        responses_map[single_response.get("id")] = single_response

            # 3. PREPARAR SUBIDAS A S3
            s3_upload_tasks = []
            valid_charts_metadata = []

            for meta in download_tasks_meta:
                req_id_str = meta["id"]
                res = responses_map.get(req_id_str)

                if not res or res.get("status") != 200:
                    errors.append(f"Error descargando gráfico '{meta['title']}'. Status: {res.get('status') if res else 'Timeout'}")
                    continue

                body = res.get("body", {})
                b64_str = body.get("value")
                if not b64_str: continue
                image_bytes = base64.b64decode(b64_str)

                normalized_code = normalize_code(meta["title"])
                if not normalized_code: continue

                code_without_dollars = normalized_code.replace("$$", "")
                prefixed_filename = f"{template_prefix}-{meta['type'].upper()}-{code_without_dollars}.png"
                dynamic_folder = f"graphs/{template_prefix}"

                # Guardamos metadata para procesar BD después
                valid_charts_metadata.append({
                    "meta": meta,
                    "normalized_code": normalized_code,
                    "prefixed_filename": prefixed_filename,
                    "size": len(image_bytes)
                })

                # Añadimos la tarea de S3
                s3_upload_tasks.append(_upload_to_s3_async(prefixed_filename, image_bytes, dynamic_folder))

            # 4. EJECUTAR SUBIDAS A S3 DE FORMA CONCURRENTE
            s3_results = await asyncio.gather(*s3_upload_tasks, return_exceptions=True) if s3_upload_tasks else []

            # 5. GUARDADO EN BD Optimizado
            for idx, s3_res in enumerate(s3_results):
                chart_data = valid_charts_metadata[idx]

                if isinstance(s3_res, Exception):
                    errors.append(f"Error S3 '{chart_data['prefixed_filename']}': {s3_res}")
                    continue

                file_url = s3_res.get("file_url")
                object_key = s3_res.get("object_key")

                resolved_url, resolved_storage_path = _resolve_media_fields(
                    template_id, chart_data['prefixed_filename'].replace('.png', ''), 
                    chart_data['prefixed_filename'], file_url, object_key
                )

                media_meta = {
                    "chart_code": chart_data['normalized_code'],
                    "chart_title": chart_data['meta']["title"],
                    "template_id": template_id,
                    "template_type": chart_data['meta']["type"],
                    "template_name": obj.nombre,
                    "size": chart_data["size"],
                }

                # Crear/Actualizar Media
                existing_media = db.execute(
                    select(Media).where(
                        (Media.filename == chart_data['prefixed_filename']) &
                        (Media.folder.like(f"%master-templates/{template_id}%")) &
                        (Media.deleted_at.is_(None))
                    )
                ).scalars().first()

                if existing_media:
                    media_obj = existing_media
                    media_obj.url = resolved_url
                    media_obj.storage_path = resolved_storage_path
                    media_obj.meta = media_meta
                else:
                    media_obj = Media(
                        filename=chart_data['prefixed_filename'], original_name=chart_data['meta']["title"], mime_type="image/png",
                        size=chart_data["size"], url=resolved_url, storage_path=resolved_storage_path,
                        folder=f"master-templates/{template_id}/{chart_data['meta']['type']}", meta=media_meta
                    )
                    db.add(media_obj)

                db.flush()

                # Crear/Actualizar TemplateCode
                code_enum = CalculationType(chart_data['meta']["type"])
                existing_tc = db.execute(
                    select(TemplateCode).where(
                        (TemplateCode.code == chart_data['normalized_code']) &
                        (TemplateCode.type == code_enum) & (TemplateCode.deleted_at.is_(None))
                    )
                ).scalars().first()

                if existing_tc:
                    tc = existing_tc
                    tc.nombre = chart_data['meta']["title"]
                    tc.hoja = chart_data['meta']["sheet"]
                else:
                    tc = TemplateCode(code=chart_data['normalized_code'], nombre=chart_data['meta']["title"], type=code_enum, hoja=chart_data['meta']["sheet"])
                    db.add(tc)

                _link_code_to_master_template(obj, tc)
                tc.template_code_image_id = media_obj.id

                extracted_charts[chart_data['meta']["type"]].append({
                    "code": chart_data['normalized_code'],
                    "filename": chart_data['prefixed_filename'],
                    "original_name": chart_data['meta']["title"],
                    "url": resolved_url,
                    "size": chart_data["size"],
                    "type": chart_data['meta']["type"],
                    "error": None
                })

            db.commit()

        except Exception as e:
            logger.error(f"[GraphAPI] Error general en extracción: {e}", exc_info=True)
            errors.append(str(e))
        finally:
            if "workbook-session-id" in headers:
                try:
                    await client.post(f"{base_url}/closeSession", headers=headers)
                except Exception:
                    pass

    return extracted_charts, total_charts, errors
