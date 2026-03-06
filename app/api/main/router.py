# app/api/main/router.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import select
from typing import List
from datetime import datetime
from ...db.database import get_db
from ...models.main import Template, TemplateComplement, Calculation, TemplateCode
from ...schemas.main import (
    TemplateCreate, TemplateUpdate, TemplateResponse,
    TemplateComplementCreate, TemplateComplementUpdate, TemplateComplementResponse,
    CalculationCreate, CalculationUpdate, CalculationResponse,
    TemplateCodeCreate, TemplateCodeUpdate, TemplateCodeResponse,
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
        select(TemplateComplement).where(TemplateComplement.deleted_at.is_(None))
    )
    complements = result.scalars().all()
    return [TemplateComplementResponse.model_validate(c) for c in complements]


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
def list_calculations(db: Session = Depends(get_db)):
    result = db.execute(select(Calculation))
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


# ==================== TEMPLATE CODES ====================
@router.get("/template-codes", response_model=List[TemplateCodeResponse])
def list_template_codes(db: Session = Depends(get_db)):
    result = db.execute(
        select(TemplateCode).where(TemplateCode.deleted_at.is_(None))
    )
    codes = result.scalars().all()
    return [_template_code_to_response(c) for c in codes]


@router.get("/template-codes/{template_code_id}", response_model=TemplateCodeResponse)
def get_template_code(template_code_id: int, db: Session = Depends(get_db)):
    code = db.get(TemplateCode, template_code_id)
    if not code or code.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Template code not found")
    return _template_code_to_response(code)


@router.post("/template-codes", response_model=TemplateCodeResponse, status_code=status.HTTP_201_CREATED)
def create_template_code(payload: TemplateCodeCreate, db: Session = Depends(get_db)):
    code = TemplateCode(
        template_code_image_id=payload.template_code_image_id,
        type=payload.type,
        hoja=payload.hoja,
        nombre=payload.nombre,
        code=payload.code,
    )
    if payload.template_ids:
        code.templates = _get_templates(db, payload.template_ids)
    db.add(code)
    db.commit()
    db.refresh(code)
    return _template_code_to_response(code)


@router.put("/template-codes/{template_code_id}", response_model=TemplateCodeResponse)
def update_template_code(
    template_code_id: int, payload: TemplateCodeUpdate, db: Session = Depends(get_db)
):
    code = db.get(TemplateCode, template_code_id)
    if not code or code.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Template code not found")

    update_data = payload.model_dump(exclude_unset=True)
    template_ids = update_data.pop("template_ids", None)

    for key, value in update_data.items():
        setattr(code, key, value)

    if template_ids is not None:
        code.templates = _get_templates(db, template_ids)

    db.commit()
    db.refresh(code)
    return _template_code_to_response(code)


@router.delete("/template-codes/{template_code_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template_code(template_code_id: int, db: Session = Depends(get_db)):
    code = db.get(TemplateCode, template_code_id)
    if not code or code.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Template code not found")
    code.deleted_at = datetime.utcnow()
    db.commit()
    return None


def _get_template_codes(db: Session, template_code_ids: List[int]):
    if not template_code_ids:
        return []
    result = db.execute(
        select(TemplateCode).where(TemplateCode.id.in_(template_code_ids))
    )
    return list(result.scalars().all())


def _get_templates(db: Session, template_ids: List[int]):
    if not template_ids:
        return []
    result = db.execute(
        select(Template).where(Template.id.in_(template_ids))
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


def _template_code_to_response(code: TemplateCode) -> TemplateCodeResponse:
    return TemplateCodeResponse(
        id=code.id,
        template_code_image_id=code.template_code_image_id,
        type=code.type.value,
        hoja=code.hoja,
        nombre=code.nombre,
        code=code.code,
        template_ids=[template.id for template in code.templates],
        created_at=code.created_at,
        updated_at=code.updated_at,
        deleted_at=code.deleted_at,
    )
