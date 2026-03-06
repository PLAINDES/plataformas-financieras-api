import json
import os

from sqlalchemy.orm import Session

from app.models.cms import Site 
from .base_seeder import BaseSeeder


class SitesSeeder(BaseSeeder):
    def __init__(self, db: Session):
        super().__init__(db)
        self._data_path = os.path.join(os.path.dirname(__file__), "data", "site_settings.json")

    def run(self):
        print("🌱 Seeding site settings...")

        with open(self._data_path, "r", encoding="utf-8") as f:
            settings_data = json.load(f)

        for setting_data in settings_data:
            existing = self.db.query(Site).filter(
                Site.id == setting_data["id"]
            ).first()

            if existing:
                self.log(f"⏭️  Site setting '{setting_data['name']}' already exists, skipping.")
                continue

            setting = Site(
                id=setting_data["id"],
                name=setting_data["name"],
                site_id=setting_data.get("site_id", 1),
                page_id=setting_data.get("page_id"),
                logo=setting_data.get("logo"),
                settings=setting_data.get("settings"),
            )

            self.db.add(setting)
            self.log(f"✅ Site setting '{setting_data['name']}' created.")

        self.db.commit()
        print("✅ Site settings seeded.\n")