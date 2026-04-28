# tests/api/main/test_master_templates.py
import pytest
from fastapi.testclient import TestClient

# Ajusta esto si tu app usa un prefijo global como /api/v1
PREFIX = "/api/v1/main/master-templates"

def test_create_master_template(client: TestClient):
    payload = {
        "nombre": "Plantilla Contable",
        "description": "Plantilla de prueba para pytest",
        "is_default": False,
    }

    response = client.post(PREFIX, json=payload)
    assert response.status_code == 201, f"Error: {response.text}"

    data = response.json()
    assert data["nombre"] == "Plantilla Contable"
    assert data["description"] == "Plantilla de prueba para pytest"
    assert "id" in data

def test_create_master_template_validation_error(client: TestClient):
    payload = {
        "nombre": "Ab", # Error intencional: menos de 3 caracteres
    }
    response = client.post(PREFIX, json=payload)
    assert response.status_code == 422
    assert "Nombre requiere >= 3 caracteres" in response.text

def test_list_master_templates(client: TestClient):
    response = client.get(PREFIX)
    assert response.status_code == 200

    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1 # Debe haber al menos la que creamos en el test anterior

def test_get_single_master_template(client: TestClient):
    # Primero listamos para obtener un ID válido
    templates = client.get(PREFIX).json()
    target_id = templates[0]["id"]

    response = client.get(f"{PREFIX}/{target_id}")
    assert response.status_code == 200
    assert response.json()["id"] == target_id

def test_update_master_template(client: TestClient):
    templates = client.get(PREFIX).json()
    target_id = templates[0]["id"]

    update_payload = {
        "nombre": "Plantilla Contable Actualizada",
    }

    response = client.put(f"{PREFIX}/{target_id}", json=update_payload)
    assert response.status_code == 200

    data = response.json()
    assert data["nombre"] == "Plantilla Contable Actualizada"

def test_set_default_template(client: TestClient):
    templates = client.get(PREFIX).json()
    target_id = templates[0]["id"]

    response = client.post(f"{PREFIX}/{target_id}/set-default")
    assert response.status_code == 200
    assert response.json()["is_default"] is True

def test_delete_master_template(client: TestClient):
    templates = client.get(PREFIX).json()
    target_id = templates[0]["id"]

    response = client.delete(f"{PREFIX}/{target_id}")
    assert response.status_code == 204

    # Verificar que ya no existe (Borrado lógico)
    get_response = client.get(f"{PREFIX}/{target_id}")
    assert get_response.status_code == 404
