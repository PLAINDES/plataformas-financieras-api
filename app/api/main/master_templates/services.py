import asyncio
import base64
import io
import logging
import re
from pathlib import Path
from typing import Optional
import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.constants import TEMPLATE_SHEET_TO_TYPE
from app.core.config import settings
from app.models.cms import Media
from app.models.main import CalculationType, TemplateCode
from app.models.templates import MasterTemplate
from app.services.aws_service import s3_service
from app.services.template_code_extractor import normalize_code

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


def _link_code_to_master_template(
    master_template: MasterTemplate, code: TemplateCode
) -> None:
    if code not in master_template.template_codes:
        master_template.template_codes.append(code)


def _resolve_media_fields(
    template_id: int,
    prefixed_stem: str,
    prefixed_filename: str,
    file_url: Optional[str],
    object_key: Optional[str],
) -> tuple[str, str]:
    fallback_url = f"/api/v1/main/master-templates/chart-file/{prefixed_stem}"
    fallback_storage_path = (
        object_key or f"master-templates/{template_id}/{prefixed_filename}"
    )
    return (file_url or fallback_url, fallback_storage_path)


def _clear_user_default_templates(
    db: Session, user_id: int, exclude_template_id: Optional[int] = None
) -> None:
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
    active_templates = (
        db.execute(
            select(MasterTemplate)
            .where(
                (MasterTemplate.deleted_at.is_(None))
                & (MasterTemplate.created_by_user_id == user_id)
            )
            .order_by(MasterTemplate.created_at.desc())
        )
        .scalars()
        .all()
    )

    if not active_templates or any(t.is_default for t in active_templates):
        return
    active_templates[0].is_default = True


def _process_and_save_cell_codes(
    db: Session,
    obj: MasterTemplate,
    extraction_result: dict,
    old_code_sets: dict = None,
) -> tuple[dict, dict]:
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
            existing = (
                db.execute(
                    select(TemplateCode).where(
                        (TemplateCode.code == cn) & (TemplateCode.type == code_enum)
                    )
                )
                .scalars()
                .first()
            )

            if existing:
                existing.deleted_at = None
                existing.nombre = data.get("nombre", "Sin nombre")
                existing.hoja = data.get("hoja")
                existing.value = data.get("value")
                if data.get("coordinate"):
                    existing.coordinate = data.get("coordinate")
                tc = existing
            else:
                tc = TemplateCode(
                    code=cn,
                    nombre=data.get("nombre", "Sin nombre"),
                    type=code_enum,
                    hoja=data.get("hoja"),
                    value=data.get("value"),
                    coordinate=data.get("coordinate"),
                )
                db.add(tc)

            _link_code_to_master_template(obj, tc)
            db.commit()
            db.refresh(tc)

            code_resp = {
                "id": tc.id,
                "code": tc.code,
                "nombre": tc.nombre,
                "hoja": tc.hoja,
                "type": template_type,
                "value": tc.value,
                "coordinate": tc.coordinate,
            }
            created_codes[template_type].append(code_resp)

            if cn not in old_sets.get(template_type, set()):
                new_codes_only[template_type].append(cn)

    return created_codes, new_codes_only


# === HELPER NATIVO PARA GRÁFICOS (GRAPH API) ==================================


async def _extract_and_save_charts_via_com(
    db: Session, template_id: int, obj: MasterTemplate, content: bytes
):
    """Export charts through the native COM service and persist them in S3."""
    try:
        response = await _request_com_charts(content)
    except Exception as exc:
        return {"valora": [], "kapital": []}, 0, [str(exc)]

    extracted = {"valora": [], "kapital": []}
    errors = []
    template_prefix = _normalize_template_name(obj.nombre)
    for chart in response.get("charts", []):
        sheet = chart.get("sheet", "")
        template_type = TEMPLATE_SHEET_TO_TYPE.get(sheet)
        if not template_type:
            continue
        title = chart.get("name") or "chart"
        normalized_code = normalize_code(title)
        if not normalized_code:
            continue
        try:
            image_bytes = base64.b64decode(chart["image_base64"])
            filename = f"{template_prefix}-{template_type.upper()}-{normalized_code.replace('$$', '')}.png"
            uploaded = await _upload_to_s3_async(filename, image_bytes, f"graphs/{template_prefix}")
            media = Media(
                filename=filename,
                original_name=title,
                mime_type="image/png",
                size=len(image_bytes),
                url=uploaded.get("file_url") or f"/api/v1/main/master-templates/chart-file/{filename[:-4]}",
                storage_path=uploaded.get("object_key") or f"graphs/{template_prefix}/{filename}",
                folder=f"master-templates/{template_id}/{template_type}",
                meta={"chart_code": normalized_code, "chart_title": title, "template_id": template_id, "template_type": template_type, "template_name": obj.nombre, "size": len(image_bytes)},
            )
            db.add(media)
            db.flush()
            code = db.execute(select(TemplateCode).where((TemplateCode.code == normalized_code) & (TemplateCode.type == CalculationType(template_type)) & (TemplateCode.deleted_at.is_(None)))).scalars().first()
            if not code:
                code = TemplateCode(code=normalized_code, nombre=title, type=CalculationType(template_type), hoja=sheet)
                db.add(code)
                db.flush()
            code.template_code_image_id = media.id
            _link_code_to_master_template(obj, code)
            extracted[template_type].append({"code": normalized_code, "filename": filename, "original_name": title, "url": media.url, "size": len(image_bytes), "type": template_type, "error": None})
        except Exception as exc:
            errors.append(f"{title}: {exc}")
    db.commit()
    return extracted, len(response.get("charts", [])), errors


async def _request_com_charts(content: bytes) -> dict:
    encoded = base64.b64encode(content).decode("ascii")
    headers = {"X-API-Key": settings.WEB_SERVICE_API_KEY} if settings.WEB_SERVICE_API_KEY else {}
    async with httpx.AsyncClient(timeout=300) as client:
        response = await client.post(
            f"{settings.WEB_SERVICE_URL.rstrip('/')}/api/v1/templates/extract-charts",
            json={"template_base64": encoded},
            headers=headers,
        )
        response.raise_for_status()
        return response.json()
