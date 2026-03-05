# app/repositories/auditory_repository.py
from sqlalchemy.orm import Session
from typing import List, Optional
from ..models.cms import Auditory


class AuditoryRepository:

    def __init__(self, db: Session):
        self.db = db

    def create_log( self, content_id: int, data_snapshot: dict, author_id: Optional[int] = None, title: str = "", ) -> Auditory:
        log = Auditory(
            content_id=content_id,
            title=title,
            author_id=author_id,
            data=data_snapshot,
            is_visible=True,
        )
        self.db.add(log)
        self.db.flush()
        return log

    def get_by_content_id(self, content_id: int) -> List[Auditory]:
        return (
            self.db.query(Auditory)
            .filter(Auditory.content_id == content_id)
            .order_by(Auditory.created_at.desc())
            .all()
        )

    def get_by_id(self, log_id: int) -> Optional[Auditory]:
        return self.db.query(Auditory).filter(Auditory.id == log_id).first()