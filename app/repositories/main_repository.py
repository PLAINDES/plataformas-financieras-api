# app/repositories/main_repository.py
from sqlalchemy.orm import Session
from sqlalchemy import select
from typing import Optional, List
from app.models.main import Calculation
from app.models.main import TemplateComplement, TemplateCode
from app.models.templates import MasterTemplate



class MainRepository:
    """Repositorio para entidades main_*"""

    def __init__(self, db: Session):
        self.db = db

    def get_template_by_id(self, template_id: int) -> Optional[MasterTemplate]:
        result = self.db.execute(
            select(MasterTemplate).where(MasterTemplate.id == template_id)
        )
        return result.scalar_one_or_none()

    def get_all_templates(self) -> List[MasterTemplate]:
        result = self.db.execute(select(MasterTemplate))
        return list(result.scalars().all())

    def get_template_complement_by_id(self, complement_id: int) -> Optional[TemplateComplement]:
        result = self.db.execute(
            select(TemplateComplement).where(TemplateComplement.id == complement_id)
        )
        return result.scalar_one_or_none()

    def get_calculation_by_id(self, calculation_id: int) -> Optional[Calculation]:
        result = self.db.execute(
            select(Calculation).where(Calculation.id == calculation_id)
        )
        return result.scalar_one_or_none()

    def get_template_code_by_id(self, template_code_id: int) -> Optional[TemplateCode]:
        result = self.db.execute(
            select(TemplateCode).where(TemplateCode.id == template_code_id)
        )
        return result.scalar_one_or_none()
