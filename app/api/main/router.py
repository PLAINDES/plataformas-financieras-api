# app/api/main/router.py
import os
import logging
from typing import List, Optional, Any
from datetime import datetime
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import select, or_
from app.models.cms import Media
from app.db.database import get_db
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, Query
from fastapi.encoders import jsonable_encoder
from app.services.query_service import apply_filters
from app.models.main import (
    TemplateComplement,
    Calculation,
    Report,
    Cover,
    CalculationType,
)
from app.api.main.calculations.router import get_default_or_latest_master_template
logger = logging.getLogger(__name__)
from app.services.aws_service import s3_service
from app.schemas.main import (
    ReportUpdate,
    TemplateComplementCreate, TemplateComplementUpdate, TemplateComplementResponse
)

router = APIRouter(prefix="/main", tags=["Main"])

def _get_latest_calculation_by_user_and_type(
    db: Session, user_id: int, calc_type: CalculationType
) -> Calculation | None:
    return (
        db.execute(
            select(Calculation)
            .where(Calculation.user_id == user_id, Calculation.type == calc_type)
            .order_by(Calculation.updated_at.desc(), Calculation.id.desc())
        )
        .scalars()
        .first()
    )


@router.get("/health")
def main_health():
    return {"status": "ok"}

# ==================== TEMPLATE COMPLEMENTS ====================
@router.get("/template-complements", response_model=List[TemplateComplementResponse])
def list_template_complements(db: Session = Depends(get_db)):
    result = db.execute(
        select(TemplateComplement)
        .where(TemplateComplement.deleted_at.is_(None))
        .order_by(TemplateComplement.created_at.desc())
    )
    complement = result.scalars().first()
    return [TemplateComplementResponse.model_validate(complement)] if complement else []

@router.get("/template-complements/{complement_id}", response_model=TemplateComplementResponse)
def get_template_complement_by_id(complement_id: int, db: Session = Depends(get_db)):
    complement = db.get(TemplateComplement, complement_id)
    if not complement or complement.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Template complement not found")
    return TemplateComplementResponse.model_validate(complement)


@router.get("/template-complements/by-name/{complement_name}")
def get_template_complement(
    complement_name: str,
    only_name: bool = Query(False, alias="only-name"),
    only_date: bool = Query(False, alias="only-date"),
    country: Optional[str] = Query(None),
    year: Optional[int] = Query(None),
    period: Optional[str] = Query(None),
    db: Session = Depends(get_db)
    ) -> Any:

    if only_name and complement_name != "damodaran":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El query parameter 'only-name' es exclusivo para el complemento 'damodaran'."
        )

    if only_date and complement_name != "rf":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El query parameter 'only-date' es exclusivo para el complemento 'rf'."
        )

    result = db.execute(
        select(TemplateComplement)
        .where(TemplateComplement.nombre == complement_name)
        .where(TemplateComplement.deleted_at.is_(None))
        .order_by(TemplateComplement.created_at.desc())
    )
    complement = result.scalars().first()

    if not complement:
        return []

    data_list = complement.data if isinstance(complement.data, list) else []

    # ==========================================
    # Extracción exacta de valor
    # ==========================================
    if country and year:
        # 1. Normalizar los parámetros que vienen de la URL
        search_year = str(year).replace(".0", "").strip()
        search_country = str(country).strip().lower()
        search_period = str(period).strip().upper() if period else None

        if complement_name == "ir":
            for item in data_list:
                # 2. Normalizar la data que viene de la BD (Excel)
                db_fecha = str(item.get("fecha", "")).replace(".0", "").strip()
                db_pais = str(item.get("pais", "")).strip().lower()

                if db_fecha == search_year and db_pais == search_country:
                    return {"valor": item.get("valor")}
            return {"valor": None}

        if complement_name == "devaluacion" and search_period:
            for item in data_list:
                db_fecha = str(item.get("fecha", "")).replace(".0", "").strip()
                db_periodo = str(item.get("periodo", "")).strip().upper()

                if db_fecha == search_year and db_periodo == search_period:
                    # Buscar la llave del país ignorando mayúsculas y espacios
                    country_key = next(
                        (k for k in item.keys() if str(k).strip().lower() == search_country), 
                        None
                    )
                    if country_key:
                        return {"valor": item.get(country_key)}

            # Si termina el bucle y no hay match
            return {"valor": None}

    # =====================
    # Lógica Existente
    # =====================
    if only_name:
        # 1. Extraer y limpiar espacios en blanco a los lados
        industrias_crudas = [
            str(item.get("industria")).strip()
            for item in data_list 
            if isinstance(item, dict) and item.get("industria")
        ]
        # 2. Eliminar los duplicados (por los años) y ordenar alfabéticamente
        return sorted(list(set(industrias_crudas)))

    if only_date:
        fechas_crudas = [
            str(item.get("fecha")).strip()
            for item in data_list 
            if isinstance(item, dict) and item.get("fecha")
        ]
        fechas_unicas = list(set(fechas_crudas))

        def parse_date_for_sort(date_str):
            try:
                return datetime.strptime(date_str, "%d/%m/%Y")
            except ValueError:
                pass
            try:
                return datetime.strptime(date_str, "%Y")
            except ValueError:
                return datetime.min

        fechas_unicas.sort(key=parse_date_for_sort, reverse=True)
        return fechas_unicas

    return [TemplateComplementResponse.model_validate(complement)]


@router.post(
    "/template-complements",
    response_model=TemplateComplementResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_template_complement(payload: TemplateComplementCreate, db: Session = Depends(get_db)):
    """
    Creates a new complement. Soft-deletes any existing complement with the same nombre
    so that only one active record per nombre exists at a time.
    """
    # Soft-delete all previous records with the same nombre
    old_records = db.execute(
        select(TemplateComplement)
        .where(TemplateComplement.nombre == payload.nombre)
        .where(TemplateComplement.deleted_at.is_(None))
    ).scalars().all()

    merged_data = payload.data

    # Lógica de Merge si ya existe historial
    if old_records and payload.nombre in ["damodaran", "riesgo", "tax"]:
        old_record = old_records[0] # El activo más reciente
        old_data = old_record.data if isinstance(old_record.data, list) else []
        new_data = payload.data if isinstance(payload.data, list) else []

        # Extraer los años que vienen en el nuevo Excel para no duplicarlos
        incoming_years = {str(item.get("fecha")) for item in new_data if item.get("fecha")}

        # Retener solo los datos del JSON antiguo que NO correspondan a los años subidos
        # (Esto permite actualizar un año si se vuelve a subir)
        retained_data = [
            item for item in old_data
            if str(item.get("fecha")) not in incoming_years
        ]

        # Combinar el historial retenido con la nueva carga
        merged_data = retained_data + new_data

    # Marcar como eliminados lógicamente los registros anteriores
    for old in old_records:
        old.deleted_at = datetime.utcnow()

    # Inyectar la data fusionada en el payload antes de guardar
    payload_dict = payload.model_dump()
    payload_dict["data"] = merged_data

    complement = TemplateComplement(**payload_dict)
    db.add(complement)
    db.commit()
    db.refresh(complement)

    return TemplateComplementResponse.model_validate(complement)


@router.put("/template-complements/{complement_id}", response_model=TemplateComplementResponse)
def update_template_complement(
    complement_id: int, payload: TemplateComplementUpdate, db: Session = Depends(get_db)
):
    complement = db.get(TemplateComplement, complement_id)
    if not complement or complement.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Template complement not found")
    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(complement, key, value)
    db.commit()
    db.refresh(complement)
    return TemplateComplementResponse.model_validate(complement)


@router.delete("/template-complements/{complement_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template_complement(complement_id: int, db: Session = Depends(get_db)):
    complement = db.get(TemplateComplement, complement_id)
    if not complement or complement.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Template complement not found")
    complement.deleted_at = datetime.utcnow()
    db.commit()
    return None

# ==================== REPORTS ====================

@router.get("/reports")
def list_reports(
    limit: Optional[int] = None,
    page: Optional[int] = None,
    search: Optional[str] = None,
    type: Optional[str] = None,
    activo: Optional[bool] = 1,
    db: Session = Depends(get_db),
):
    base_query = select(Report)

    eager = [
        joinedload(Report.portada).joinedload(Cover.portada),
        joinedload(Report.portada).joinedload(Cover.primer_imagen_footer),
        joinedload(Report.portada).joinedload(Cover.segundo_imagen_footer),
        joinedload(Report.portada).joinedload(Cover.logo_superior),
        joinedload(Report.portada).joinedload(Cover.imagen_central),
        joinedload(Report.portada).joinedload(Cover.logo_inferior),
        joinedload(Report.portada).joinedload(Cover.imagen_fondo),
    ]

    params = {
        "limit": limit,
        "page": page,
        "search": search,
        "type": type,
        "activo": activo,
    }

    query = apply_filters(
        base_query,
        Report,
        params,
        search_fields=["nombre", "contenido", "sector_empresa"],
        enum_fields={"type": CalculationType},
        eager_loads=eager,
    )

    # order newest first
    query = query.order_by(Report.created_at.desc(), Report.id.desc())

    result = db.execute(query)
    reports = result.unique().scalars().all()
    return [_report_to_response(r) for r in reports]


@router.get("/reports/get-current-codes")
async def get_current_codes(db: Session = Depends(get_db)):
    """
    Obtiene la plantilla maestra por defecto (si existe), y si no, usa
    la más reciente no borrada. Devuelve sus códigos reusando la lógica
    de `get_template_codes`.
    """
    obj = get_default_or_latest_master_template(db)

    if not obj:
        raise HTTPException(status_code=404, detail="No master template found")

    from .master_templates import router as master_templates_router

    # Get template codes (async) and chart images (sync) from the master templates router
    codes_payload = await master_templates_router.get_template_codes(obj.id, db)
    images_payload = master_templates_router.get_template_chart_images(obj.id, db)

    # Build a map code -> image url (codes are returned as strings like $$CODE$$)
    image_map = {}
    for t in ("valora", "kapital"):
        for img in images_payload.get(t, []):
            code = img.get("code")
            if code:
                image_map[code] = img.get("url")

    # Attach image url to each template code if available
    def attach_urls(codes_list, t):
        # Return a minimal object for each code with only the fields the frontend expects
        result = []
        for c in codes_list:
            # c may be a Pydantic model or dict or a plain string
            if not c:
                continue
            if isinstance(c, str):
                code_val = c
                entry = {
                    "id": -1,
                    "nombre": c,
                    "code": code_val,
                    "type": t,
                    "hoja": None,
                }
            else:
                try:
                    c_dict = c.model_dump() if hasattr(c, "model_dump") else dict(c)
                except Exception:
                    c_dict = dict(c)
                entry = {
                    "id": c_dict.get("id", -1),
                    "nombre": c_dict.get("nombre") or c_dict.get("original_name") or c_dict.get("filename") or c_dict.get("code"),
                    "code": c_dict.get("code"),
                    "type": t,
                    "hoja": c_dict.get("hoja"),
                }

            img_url = image_map.get(entry.get("code"))
            if img_url:
                entry["template_code_image_url"] = img_url

            result.append(entry)
        return result

    # `get_template_codes` returns keys: template_id, template_name, codes, statistics
    codes_block = codes_payload.get("codes", {}) if isinstance(codes_payload, dict) else {}

    return {
        "template_id": codes_payload.get("template_id"),
        "template_name": codes_payload.get("template_name"),
        "extracted_codes": {
            "valora": attach_urls(codes_block.get("valora", []), "valora"),
            "kapital": attach_urls(codes_block.get("kapital", []), "kapital"),
        },
        "extracted_chart_codes": None,
        "extracted_chart_images": images_payload,
        "chart_extraction_stats": None,
        "statistics": codes_payload.get("statistics"),
        "processed_sheets": None,
    }


@router.get("/reports/get-default-template-codes")
async def get_default_template_codes(db: Session = Depends(get_db)):
    """Alias explícito para obtener los códigos de la plantilla maestra por defecto."""
    return await get_current_codes(db)




@router.get("/reports/{report_id}")
def get_report(report_id: int, db: Session = Depends(get_db)):
    result = db.execute(
        select(Report)
        .where(Report.id == report_id, Report.deleted_at.is_(None))
        .options(
            joinedload(Report.portada).joinedload(Cover.portada),
            joinedload(Report.portada).joinedload(Cover.primer_imagen_footer),
            joinedload(Report.portada).joinedload(Cover.segundo_imagen_footer),
            joinedload(Report.portada).joinedload(Cover.logo_superior),
            joinedload(Report.portada).joinedload(Cover.imagen_central),
            joinedload(Report.portada).joinedload(Cover.logo_inferior),
            joinedload(Report.portada).joinedload(Cover.imagen_fondo),
        )
    )
    report = result.unique().scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return _report_to_response(report)


@router.post("/reports")
def create_report(data: ReportUpdate, db: Session = Depends(get_db)):
    # Require at least a nombre for creation
    if not data.nombre:
        raise HTTPException(status_code=400, detail="Field 'nombre' is required")

    # Try to pick a default master template for new reports
    template = get_default_or_latest_master_template(db)
    if not template:
        raise HTTPException(
            status_code=400,
            detail="No master template available to assign to the report",
        )

    report = Report(
        template_id=template.id,
        nombre=data.nombre,
        precio=data.precio,
        moneda=data.moneda or "SOLES",
        sector_empresa=data.sector_empresa,
        bono_ajustado=data.bono_ajustado,
        link_pago=data.link_pago,
        contenido=data.contenido,
        contentEditor=data.contentEditor,
        portada_id=data.portada_id,
        activo=data.activo if data.activo is not None else True,
        type=CalculationType(data.type) if getattr(data, "type", None) else CalculationType.KAPITAL,
    )

    db.add(report)
    db.commit()
    db.refresh(report)
    logger.info(f"_report_to_response(report): {_report_to_response(report)}")
    response =_report_to_response(report)
    return jsonable_encoder(response)


@router.put("/reports/{report_id}")
def update_report(report_id: int, data: ReportUpdate, db: Session = Depends(get_db)):

    result = db.execute(
        select(Report)
        .where(Report.id == report_id, Report.deleted_at.is_(None))
        .options(joinedload(Report.portada))
    )
    report = result.unique().scalar_one_or_none()

    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    update_dict = data.model_dump(exclude_unset=True, exclude={"cover_data"})

    for key, value in update_dict.items():
        if key == "type" and value is not None:
            try:
                setattr(report, key, CalculationType(value))
            except Exception:
                setattr(report, key, value)
        else:
            setattr(report, key, value)

    if data.cover_data and report.portada:
        cover_dict = data.cover_data.model_dump(exclude_unset=True)
        for key, value in cover_dict.items():
            setattr(report.portada, key, value)

    try:
        db.commit()
        db.refresh(report)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Error al actualizar: {str(e)}")

    return _report_to_response(report)


STORAGE_DIR = os.path.join(os.path.dirname(__file__), "../../files")

@router.post("/reports/{report_id}/upload", status_code=status.HTTP_200_OK)
async def upload_report_file(
    report_id: int,
    file: UploadFile = File(...),
    html: str = Form(...),
    db: Session = Depends(get_db),
):
    report = db.get(Report, report_id)
    if not report or report.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Report not found")

    print("STORAGE_DIR:", STORAGE_DIR)
    print("STORAGE_DIR absoluto:", os.path.abspath(STORAGE_DIR))
    print("__file__:", __file__)

    os.makedirs(STORAGE_DIR, exist_ok=True)

    filename = f"Reporte-{report_id}.pdf"
    pdf_path = os.path.join(STORAGE_DIR, filename)

    with open(pdf_path, "wb") as f:
        f.write(await file.read())

    html_path = os.path.join(STORAGE_DIR, f"Reporte-{report_id}.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    report.file = filename
    # persist editor content to the DB as well
    try:
        report.contentEditor = html
    except Exception:
        pass
    db.commit()
    return {"message": "Archivo guardado", "file": filename}


@router.get("/reports/{report_id}/content")
def get_report_content(report_id: int, db: Session = Depends(get_db)):
    report = db.get(Report, report_id)
    if not report or report.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Report not found")

    html_path = os.path.join(STORAGE_DIR, f"Reporte-{report_id}.html")
    if not os.path.exists(html_path):
        return {"html": ""}

    with open(html_path, "r", encoding="utf-8") as f:
        return {"html": f.read()}


# ==================== COVERS ====================

@router.get("/covers")
def list_covers(db: Session = Depends(get_db)):
    result = db.execute(
        select(Cover)
        .where(Cover.deleted_at.is_(None))
        .options(
            joinedload(Cover.portada),
            joinedload(Cover.primer_imagen_footer),
            joinedload(Cover.segundo_imagen_footer),
            joinedload(Cover.logo_superior),
            joinedload(Cover.imagen_central),
            joinedload(Cover.logo_inferior),
            joinedload(Cover.imagen_fondo),
        )
    )
    covers = result.unique().scalars().all()
    return [_cover_to_dict(c) for c in covers]


@router.get("/covers/{cover_id}")
def get_cover(cover_id: int, db: Session = Depends(get_db)):
    result = db.execute(
        select(Cover)
        .where(Cover.id == cover_id, Cover.deleted_at.is_(None))
        .options(
            joinedload(Cover.portada),
            joinedload(Cover.primer_imagen_footer),
            joinedload(Cover.segundo_imagen_footer),
            joinedload(Cover.logo_superior),
            joinedload(Cover.imagen_central),
            joinedload(Cover.logo_inferior),
            joinedload(Cover.imagen_fondo),
        )
    )
    cover = result.unique().scalar_one_or_none()
    if not cover:
        raise HTTPException(status_code=404, detail="Cover not found")
    return _cover_to_dict(cover)


def _create_media_from_upload(db: Session, file: UploadFile) -> Optional[int]:
    if not file or not file.filename:
        return None
        
    try:
        s3_result = s3_service.upload_file(file, folder="covers")
    except Exception as e:
        # Si falla AWS S3, lanzamos un 400 para que el frontend lo pueda mostrar
        # y no cause un 500 que rompe los headers CORS.
        raise HTTPException(status_code=400, detail=f"Error subiendo archivo a AWS S3: {str(e)}")
    
    media = Media(
        filename=s3_result["object_key"].split("/")[-1],
        original_name=file.filename,
        mime_type=file.content_type or "application/octet-stream",
        url=s3_result["file_url"],
        storage_path=s3_result["object_key"],
        folder="/covers"
    )
    db.add(media)
    db.flush()  # Para obtener el ID generado
    return media.id


@router.post("/covers", status_code=status.HTTP_201_CREATED)
def create_cover(
    nombre: str = Form(...),
    tipo: str = Form(...),
    portada_id: Optional[int] = Form(None),
    primer_imagen_footer_id: Optional[int] = Form(None),
    segundo_imagen_footer_id: Optional[int] = Form(None),
    logo_superior_id: Optional[int] = Form(None),
    imagen_central_id: Optional[int] = Form(None),
    logo_inferior_id: Optional[int] = Form(None),
    imagen_fondo_id: Optional[int] = Form(None),

    portada: Optional[UploadFile] = File(None),
    primer_imagen_footer: Optional[UploadFile] = File(None),
    segundo_imagen_footer: Optional[UploadFile] = File(None),
    logo_superior: Optional[UploadFile] = File(None),
    imagen_central: Optional[UploadFile] = File(None),
    logo_inferior: Optional[UploadFile] = File(None),
    imagen_fondo: Optional[UploadFile] = File(None),

    db: Session = Depends(get_db)
):
    # Subir nuevos archivos a S3 y crear los Media correspondientes si existen
    if portada and portada.filename:
        portada_id = _create_media_from_upload(db, portada)
    if primer_imagen_footer and primer_imagen_footer.filename:
        primer_imagen_footer_id = _create_media_from_upload(db, primer_imagen_footer)
    if segundo_imagen_footer and segundo_imagen_footer.filename:
        segundo_imagen_footer_id = _create_media_from_upload(db, segundo_imagen_footer)
    if logo_superior and logo_superior.filename:
        logo_superior_id = _create_media_from_upload(db, logo_superior)
    if imagen_central and imagen_central.filename:
        imagen_central_id = _create_media_from_upload(db, imagen_central)
    if logo_inferior and logo_inferior.filename:
        logo_inferior_id = _create_media_from_upload(db, logo_inferior)
    if imagen_fondo and imagen_fondo.filename:
        imagen_fondo_id = _create_media_from_upload(db, imagen_fondo)

    cover = Cover(
        nombre=nombre,
        tipo=tipo,
        portada_id=portada_id,
        primer_imagen_footer_id=primer_imagen_footer_id,
        segundo_imagen_footer_id=segundo_imagen_footer_id,
        logo_superior_id=logo_superior_id,
        imagen_central_id=imagen_central_id,
        logo_inferior_id=logo_inferior_id,
        imagen_fondo_id=imagen_fondo_id,
    )
    db.add(cover)
    db.commit()
    db.refresh(cover)
    return get_cover(cover.id, db)


@router.put("/covers/{cover_id}")
def update_cover(
    cover_id: int,
    nombre: Optional[str] = Form(None),
    tipo: Optional[str] = Form(None),
    portada_id: Optional[int] = Form(None),
    primer_imagen_footer_id: Optional[int] = Form(None),
    segundo_imagen_footer_id: Optional[int] = Form(None),
    logo_superior_id: Optional[int] = Form(None),
    imagen_central_id: Optional[int] = Form(None),
    logo_inferior_id: Optional[int] = Form(None),
    imagen_fondo_id: Optional[int] = Form(None),

    portada: Optional[UploadFile] = File(None),
    primer_imagen_footer: Optional[UploadFile] = File(None),
    segundo_imagen_footer: Optional[UploadFile] = File(None),
    logo_superior: Optional[UploadFile] = File(None),
    imagen_central: Optional[UploadFile] = File(None),
    logo_inferior: Optional[UploadFile] = File(None),
    imagen_fondo: Optional[UploadFile] = File(None),

    db: Session = Depends(get_db),
):
    cover = db.get(Cover, cover_id)
    if not cover or cover.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Cover not found")

    now = datetime.utcnow()

    # Si vienen nuevos archivos, intentar eliminar los antiguos en S3
    # y marcar los Media existentes como borrados (soft-delete) antes de subir
    if portada and portada.filename:
        existing = getattr(cover, "portada")
        if existing:
            try:
                s3_service.delete_file(existing.storage_path)
            except Exception:
                pass
            existing.deleted_at = now
            db.add(existing)
            cover.portada_id = None
        portada_id = _create_media_from_upload(db, portada)

    if primer_imagen_footer and primer_imagen_footer.filename:
        existing = getattr(cover, "primer_imagen_footer")
        if existing:
            try:
                s3_service.delete_file(existing.storage_path)
            except Exception:
                pass
            existing.deleted_at = now
            db.add(existing)
            cover.primer_imagen_footer_id = None
        primer_imagen_footer_id = _create_media_from_upload(db, primer_imagen_footer)

    if segundo_imagen_footer and segundo_imagen_footer.filename:
        existing = getattr(cover, "segundo_imagen_footer")
        if existing:
            try:
                s3_service.delete_file(existing.storage_path)
            except Exception:
                pass
            existing.deleted_at = now
            db.add(existing)
            cover.segundo_imagen_footer_id = None
        segundo_imagen_footer_id = _create_media_from_upload(db, segundo_imagen_footer)

    if logo_superior and logo_superior.filename:
        existing = getattr(cover, "logo_superior")
        if existing:
            try:
                s3_service.delete_file(existing.storage_path)
            except Exception:
                pass
            existing.deleted_at = now
            db.add(existing)
            cover.logo_superior_id = None
        logo_superior_id = _create_media_from_upload(db, logo_superior)

    if imagen_central and imagen_central.filename:
        existing = getattr(cover, "imagen_central")
        if existing:
            try:
                s3_service.delete_file(existing.storage_path)
            except Exception:
                pass
            existing.deleted_at = now
            db.add(existing)
            cover.imagen_central_id = None
        imagen_central_id = _create_media_from_upload(db, imagen_central)

    if logo_inferior and logo_inferior.filename:
        existing = getattr(cover, "logo_inferior")
        if existing:
            try:
                s3_service.delete_file(existing.storage_path)
            except Exception:
                pass
            existing.deleted_at = now
            db.add(existing)
            cover.logo_inferior_id = None
        logo_inferior_id = _create_media_from_upload(db, logo_inferior)

    if imagen_fondo and imagen_fondo.filename:
        existing = getattr(cover, "imagen_fondo")
        if existing:
            try:
                s3_service.delete_file(existing.storage_path)
            except Exception:
                pass
            existing.deleted_at = now
            db.add(existing)
            cover.imagen_fondo_id = None
        imagen_fondo_id = _create_media_from_upload(db, imagen_fondo)

    # Actualizar campos si se proporcionaron
    if nombre is not None:
        cover.nombre = nombre
    if tipo is not None:
        cover.tipo = tipo

    # Asociar nuevos media ids si fueron proporcionados
    if portada_id is not None:
        cover.portada_id = portada_id
    if primer_imagen_footer_id is not None:
        cover.primer_imagen_footer_id = primer_imagen_footer_id
    if segundo_imagen_footer_id is not None:
        cover.segundo_imagen_footer_id = segundo_imagen_footer_id
    if logo_superior_id is not None:
        cover.logo_superior_id = logo_superior_id
    if imagen_central_id is not None:
        cover.imagen_central_id = imagen_central_id
    if logo_inferior_id is not None:
        cover.logo_inferior_id = logo_inferior_id
    if imagen_fondo_id is not None:
        cover.imagen_fondo_id = imagen_fondo_id

    db.commit()
    db.refresh(cover)
    return get_cover(cover_id, db)


@router.delete("/covers/{cover_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_cover(cover_id: int, db: Session = Depends(get_db)):
    cover = db.get(Cover, cover_id)
    if not cover or cover.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Cover not found")
    now = datetime.utcnow()

    # Campos de Media relacionados con la cover
    media_fields = [
        "portada",
        "primer_imagen_footer",
        "segundo_imagen_footer",
        "logo_superior",
        "imagen_central",
        "logo_inferior",
        "imagen_fondo",
    ]

    # Intentar eliminar objetos en S3 y marcar los Media como borrados (soft-delete)
    for field in media_fields:
        media = getattr(cover, field)
        if media:
            try:
                # storage_path contiene el object key
                s3_service.delete_file(media.storage_path)
            except Exception:
                # No interrumpimos si falla la eliminación en S3; marcamos el media como borrado de todos modos
                pass

            media.deleted_at = now
            db.add(media)
            # Desasociar la media de la cover
            setattr(cover, f"{field}_id", None)

    cover.deleted_at = now
    db.commit()
    return None


# ==================== HELPER FUNCTIONS ====================

def _media_to_dict(media: Media | None) -> dict | None:
    if not media:
        return None
    return {
        "id": media.id,
        "url": media.url,
        "filename": media.filename,
        "original_name": media.original_name,
        "mime_type": media.mime_type,
        "alt_text": media.alt_text,
    }


def _cover_to_dict(cover: Cover | None) -> dict | None:
    if not cover:
        return None
    return {
        "id": cover.id,
        "nombre": cover.nombre,
        "tipo": cover.tipo.value,
        "portada": _media_to_dict(cover.portada),
        "primer_imagen_footer": _media_to_dict(cover.primer_imagen_footer),
        "segundo_imagen_footer": _media_to_dict(cover.segundo_imagen_footer),
        "logo_superior": _media_to_dict(cover.logo_superior),
        "imagen_central": _media_to_dict(cover.imagen_central),
        "logo_inferior": _media_to_dict(cover.logo_inferior),
        "imagen_fondo": _media_to_dict(cover.imagen_fondo),
    }


def _report_to_response(report: Report) -> dict:
    def _iso(v):
        try:
            return v.isoformat() if v is not None and hasattr(v, "isoformat") else v
        except Exception:
            return str(v)
    return {
        "id": report.id,
        "nombre": report.nombre,
        "file": report.file,
        "precio": float(report.precio) if report.precio is not None else None,
        "moneda": report.moneda,
        "sector_empresa": report.sector_empresa,
        "bono_ajustado": report.bono_ajustado,
        "link_pago": report.link_pago,
        "contenido": report.contenido,
        "contentEditor": report.contentEditor,
        "activo": report.activo,
        "created_at": _iso(report.created_at),
        "updated_at": _iso(report.updated_at),
        "portada": _cover_to_dict(report.portada),
    }
