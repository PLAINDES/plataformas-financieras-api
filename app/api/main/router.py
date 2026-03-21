# app/api/main/router.py
import os
from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import select, func
from app.db.database import get_db
from app.models.main import Calculation
from app.models.templates.templates import Template, TemplateComplement, TemplateCode
from app.models.main import Report, Cover
from app.models.cms import Media
from app.schemas.main import (
    ReportUpdate, TemplateCreate, TemplateUpdate, TemplateResponse,
    TemplateComplementCreate, TemplateComplementUpdate, TemplateComplementResponse,
    CalculationCreate, CalculationUpdate, CalculationResponse,
)

router = APIRouter(prefix="/main", tags=["Main"])


@router.get("/health")
def main_health():
    return {"status": "ok"}


# ==================== TEMPLATES ====================
@router.get("/templates", response_model=List[TemplateResponse])
def list_templates(db: Session = Depends(get_db)):
    result = db.execute(
        select(Template).where(Template.deleted_at.is_(None))
    )
    templates = result.scalars().all()
    return [_template_to_response(t) for t in templates]


@router.get("/templates/{template_id}", response_model=TemplateResponse)
def get_template(template_id: int, db: Session = Depends(get_db)):
    template = db.get(Template, template_id)
    if not template or template.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Template not found")
    return _template_to_response(template)


@router.post("/templates", response_model=TemplateResponse, status_code=status.HTTP_201_CREATED)
def create_template(payload: TemplateCreate, db: Session = Depends(get_db)):
    template = Template(
        nombre=payload.nombre,
        template_file_id=payload.template_file_id,
        is_default=payload.is_default,
    )
    if payload.template_code_ids:
        template.template_codes = _get_template_codes(db, payload.template_code_ids)
    db.add(template)
    db.commit()
    db.refresh(template)
    return _template_to_response(template)


@router.put("/templates/{template_id}", response_model=TemplateResponse)
def update_template(template_id: int, payload: TemplateUpdate, db: Session = Depends(get_db)):
    template = db.get(Template, template_id)
    if not template or template.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Template not found")

    update_data = payload.model_dump(exclude_unset=True)
    template_code_ids = update_data.pop("template_code_ids", None)

    for key, value in update_data.items():
        setattr(template, key, value)

    if template_code_ids is not None:
        template.template_codes = _get_template_codes(db, template_code_ids)

    db.commit()
    db.refresh(template)
    return _template_to_response(template)


@router.delete("/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(template_id: int, db: Session = Depends(get_db)):
    template = db.get(Template, template_id)
    if not template or template.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Template not found")
    template.deleted_at = datetime.utcnow()
    db.commit()
    return None

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
def get_template_complement(complement_id: int, db: Session = Depends(get_db)):
    complement = db.get(TemplateComplement, complement_id)
    if not complement or complement.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Template complement not found")
    return TemplateComplementResponse.model_validate(complement)


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

    for old in old_records:
        old.deleted_at = datetime.utcnow()

    complement = TemplateComplement(**payload.model_dump())
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


# ==================== CALCULATIONS ====================
@router.get("/calculations", response_model=List[CalculationResponse])
def list_calculations(user_id: Optional[int] = None, db: Session = Depends(get_db)):
    query = select(Calculation)
    if user_id:
        query = query.where(Calculation.user_id == user_id)
    result = db.execute(query)
    calculations = result.scalars().all()
    return [CalculationResponse.model_validate(c) for c in calculations]


@router.get("/calculations/{calculation_id}", response_model=CalculationResponse)
def get_calculation(calculation_id: int, db: Session = Depends(get_db)):
    calculation = db.get(Calculation, calculation_id)
    if not calculation:
        raise HTTPException(status_code=404, detail="Calculation not found")
    return CalculationResponse.model_validate(calculation)


@router.post("/calculations", response_model=CalculationResponse, status_code=status.HTTP_201_CREATED)
def create_calculation(payload: CalculationCreate, db: Session = Depends(get_db)):
    calculation = Calculation(**payload.model_dump())
    db.add(calculation)
    db.commit()
    db.refresh(calculation)
    return CalculationResponse.model_validate(calculation)


@router.put("/calculations/{calculation_id}", response_model=CalculationResponse)
def update_calculation(calculation_id: int, payload: CalculationUpdate, db: Session = Depends(get_db)):
    calculation = db.get(Calculation, calculation_id)
    if not calculation:
        raise HTTPException(status_code=404, detail="Calculation not found")
    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(calculation, key, value)
    db.commit()
    db.refresh(calculation)
    return CalculationResponse.model_validate(calculation)


@router.delete("/calculations/{calculation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_calculation(calculation_id: int, db: Session = Depends(get_db)):
    calculation = db.get(Calculation, calculation_id)
    if not calculation:
        raise HTTPException(status_code=404, detail="Calculation not found")
    db.delete(calculation)
    db.commit()
    return None


# ==================== REPORTS ====================

@router.get("/reports")
def list_reports(db: Session = Depends(get_db)):
    result = db.execute(
        select(Report)
        .where(Report.deleted_at.is_(None))
        .options(
            joinedload(Report.template).joinedload(Template.template_codes),
            joinedload(Report.portada).joinedload(Cover.portada),
            joinedload(Report.portada).joinedload(Cover.primer_imagen_footer),
            joinedload(Report.portada).joinedload(Cover.segundo_imagen_footer),
            joinedload(Report.portada).joinedload(Cover.logo_superior),
            joinedload(Report.portada).joinedload(Cover.imagen_central),
            joinedload(Report.portada).joinedload(Cover.logo_inferior),
            joinedload(Report.portada).joinedload(Cover.imagen_fondo),
        )
    )
    reports = result.unique().scalars().all()
    return [_report_to_response(r) for r in reports]


@router.get("/reports/{report_id}")
def get_report(report_id: int, db: Session = Depends(get_db)):
    result = db.execute(
        select(Report)
        .where(Report.id == report_id, Report.deleted_at.is_(None))
        .options(
            joinedload(Report.template).joinedload(Template.template_codes),
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

    return {"message": "Reporte actualizado correctamente"}


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


@router.post("/covers", status_code=status.HTTP_201_CREATED)
def create_cover(payload: dict, db: Session = Depends(get_db)):
    cover = Cover(
        nombre=payload["nombre"],
        tipo=payload["tipo"],
        portada_id=payload.get("portada_id"),
        primer_imagen_footer_id=payload.get("primer_imagen_footer_id"),
        segundo_imagen_footer_id=payload.get("segundo_imagen_footer_id"),
        logo_superior_id=payload.get("logo_superior_id"),
        imagen_central_id=payload.get("imagen_central_id"),
        logo_inferior_id=payload.get("logo_inferior_id"),
        imagen_fondo_id=payload.get("imagen_fondo_id"),
    )
    db.add(cover)
    db.commit()
    db.refresh(cover)
    return get_cover(cover.id, db)


@router.put("/covers/{cover_id}")
def update_cover(cover_id: int, payload: dict, db: Session = Depends(get_db)):
    cover = db.get(Cover, cover_id)
    if not cover or cover.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Cover not found")

    allowed = {
        "nombre", "tipo",
        "portada_id", "primer_imagen_footer_id", "segundo_imagen_footer_id",
        "logo_superior_id", "imagen_central_id", "logo_inferior_id", "imagen_fondo_id",
    }
    for key, value in payload.items():
        if key in allowed:
            setattr(cover, key, value)

    db.commit()
    db.refresh(cover)
    return get_cover(cover_id, db)


@router.delete("/covers/{cover_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_cover(cover_id: int, db: Session = Depends(get_db)):
    cover = db.get(Cover, cover_id)
    if not cover or cover.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Cover not found")
    cover.deleted_at = datetime.utcnow()
    db.commit()
    return None


# ==================== HELPER FUNCTIONS ====================

def _get_template_codes(db: Session, template_code_ids: List[int]):
    if not template_code_ids:
        return []
    result = db.execute(
        select(TemplateCode).where(TemplateCode.id.in_(template_code_ids))
    )
    return list(result.scalars().all())


def _template_to_response(template: Template) -> TemplateResponse:
    return TemplateResponse(
        id=template.id,
        nombre=template.nombre,
        template_file_id=template.template_file_id,
        is_default=template.is_default,
        template_code_ids=[code.id for code in template.template_codes],
        created_at=template.created_at,
        updated_at=template.updated_at,
        deleted_at=template.deleted_at,
    )

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
    template = report.template
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
        "activo": report.activo,
        "created_at": report.created_at,
        "updated_at": report.updated_at,
        "template": {
            "id": template.id,
            "nombre": template.nombre,
            "is_default": template.is_default,
            "template_codes": [
                {
                    "id": tc.id,
                    "nombre": tc.nombre,
                    "code": tc.code,
                    "type": tc.type.value,
                    "hoja": tc.hoja,
                }
                for tc in template.template_codes
            ],
        } if template else None,
        "portada": _cover_to_dict(report.portada),
    }
