import json
import os

from sqlalchemy.orm import Session

from app.models.cms import Page
from .base_seeder import BaseSeeder


class PagesSeeder(BaseSeeder):
    def __init__(self, db: Session):
        super().__init__(db)
        self._data_path = os.path.join(os.path.dirname(__file__), "data", "pages.json")

    def run(self):
        print("🌱 Seeding pages...")

        with open(self._data_path, "r", encoding="utf-8") as f:
            pages_data = json.load(f)

        for page_data in pages_data:
            existing = self.db.query(Page).filter(Page.id == page_data["id"]).first()

            if existing:
                self.log(f"⏭️  Page '{page_data['slug']}' already exists, skipping.")
                continue

            page = Page(
                id=page_data["id"],
                title=page_data["title"],
                slug=page_data["slug"],
                template=page_data.get("template"),
                parent_id=page_data.get("parent_id"),
                status=page_data.get("status", "published"),
                is_home=page_data.get("is_home", False),
                site_id=page_data.get("site_id", 1),
                settings=page_data.get("settings"),
                meta_title=page_data.get("meta_title"),
                meta_description=page_data.get("meta_description"),
                meta_image=page_data.get("meta_image"),
            )

            self.db.add(page)
            self.log(f"✅ Page '{page_data['slug']}' created.")

        self.db.commit()
        print("✅ Pages seeded.\n")