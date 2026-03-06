import json
import os

from sqlalchemy.orm import Session

from app.models.cms import Content 
from .base_seeder import BaseSeeder


class ContentsSeeder(BaseSeeder):
    def __init__(self, db: Session):
        super().__init__(db)
        self._data_path = os.path.join(os.path.dirname(__file__), "data", "contents.json")

    def run(self):
        print("🌱 Seeding contents...")

        with open(self._data_path, "r", encoding="utf-8") as f:
            contents_data = json.load(f)

        for content_data in contents_data:
            existing = self.db.query(Content).filter(
                Content.id == content_data["id"]
            ).first()

            if existing:
                self.log(f"⏭️  Content '{content_data['slug']}' already exists, skipping.")
                continue

            content = Content(
                id=content_data["id"],
                site_id=content_data.get("site_id", 1),
                parent_id=content_data.get("parent_id", 0),
                content_type_id=content_data["content_type_id"],
                slug=content_data["slug"],
                name=content_data.get("name"),
                data=content_data.get("data"),
                status=content_data.get("status", "published"),
                is_active=content_data.get("is_active", True),
            )

            self.db.add(content)
            self.log(f"✅ Content '{content_data['slug']}' (id={content_data['id']}) created.")

        self.db.commit()
        print("✅ Contents seeded.\n")