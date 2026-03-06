import json
import os

from sqlalchemy.orm import Session

from app.models.cms import ContentType 
from .base_seeder import BaseSeeder


class ContentTypesSeeder(BaseSeeder):
    def __init__(self, db: Session):
        super().__init__(db)
        self._data_path = os.path.join(os.path.dirname(__file__), "data", "content_types.json")

    def run(self):
        print("🌱 Seeding content types...")

        with open(self._data_path, "r", encoding="utf-8") as f:
            types_data = json.load(f)

        for type_data in types_data:
            existing = self.db.query(ContentType).filter(
                ContentType.id == type_data["id"]
            ).first()

            if existing:
                self.log(f"⏭️  Content type '{type_data['slug']}' already exists, skipping.")
                continue

            content_type = ContentType(
                id=type_data["id"],
                slug=type_data["slug"],
                name=type_data["name"],
                description=type_data.get("description"),
                schema=type_data.get("schema"),
                icon=type_data.get("icon"),
                is_singleton=type_data.get("is_singleton", True),
            )

            self.db.add(content_type)
            self.log(f"✅ Content type '{type_data['slug']}' (id={type_data['id']}) created.")

        self.db.commit()
        print("✅ Content types seeded.\n")