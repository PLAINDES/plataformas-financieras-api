# tests/conftest.py
import os
import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.db.database import get_db
from app.api.deps import get_current_admin, get_current_user
from app.models.user import User, UserRole

from app.core.config import settings


engine = create_engine(settings.DATABASE_URL)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@pytest.fixture
def db_session():
    """Provee una sesión de base de datos para cada test."""
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

@pytest.fixture
def client(db_session):
    """Cliente de pruebas que sobreescribe la BD y la autenticación."""
    app.dependency_overrides[get_db] = lambda: db_session

    # Simulamos usuario administrador real usando los campos exactos del modelo
    fake_user = User(
        id=1, 
        email="admin_test@gmail.com",
        name="Admin",
        role=UserRole.ADMIN,
        is_active=True,
        created_at=datetime.now(timezone.utc),
    )

    app.dependency_overrides[get_current_admin] = lambda: fake_user
    app.dependency_overrides[get_current_user] = lambda: fake_user

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()
