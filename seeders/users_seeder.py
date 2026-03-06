import json
import os

from sqlalchemy.orm import Session

from app.models.user import User, UserRole
from app.core.security import get_password_hash  
from .base_seeder import BaseSeeder


class UsersSeeder(BaseSeeder):
    def __init__(self, db: Session):
        super().__init__(db)
        self._data_path = os.path.join(os.path.dirname(__file__), "data", "users.json")

    def run(self):
        print("🌱 Seeding users...")

        with open(self._data_path, "r", encoding="utf-8") as f:
            users_data = json.load(f)

        for user_data in users_data:
            email = user_data["email"]
            existing = self.db.query(User).filter(User.email == email).first()

            if existing:
                self.log(f"⏭️  User '{email}' already exists, skipping.")
                continue

            role_value = user_data.get("role", "user")
            role = UserRole(role_value)

            user = User(
                email=email,
                password=get_password_hash(user_data["password"]),
                name=user_data["name"],
                lastname=user_data.get("lastname"),
                role=role,
                is_active=user_data.get("is_active", True),
                avatar=user_data.get("avatar"),
                settings=user_data.get("settings"),
            )

            self.db.add(user)
            self.log(f"✅ User '{email}' created with role '{role_value}'.")

        self.db.commit()
        print("✅ Users seeded.\n")