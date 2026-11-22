import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

ADMIN = ("admin_test", "Admin-Clave-Segura-123")
PROMOTOR = ("promotor_test", "Promotor-Clave-Segura-123")


@pytest.fixture()
def client(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        secret_key="clave-solo-para-pruebas-" + "x" * 32,
        admin_user=ADMIN[0], admin_password=ADMIN[1],
        promotor_user=PROMOTOR[0], promotor_password=PROMOTOR[1],
    )
    with TestClient(create_app(settings)) as c:
        yield c


def login(client, credenciales):
    r = client.post("/api/auth/login", json={"usuario": credenciales[0], "password": credenciales[1]})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def promotor(client):
    return login(client, PROMOTOR)


@pytest.fixture()
def admin(client):
    return login(client, ADMIN)


def datos_trabajador(**cambios):
    base = {
        "tipo_documento": "DNI", "numero_documento": "45678912", "nombres": "Carlos Pérez Ramos",
        "fecha_nacimiento": "1999-05-10", "celular": "987654321",
        "cruce": "Av. Javier Prado / Av. Arequipa", "horario": "manana",
    }
    base.update(cambios)
    return base


@pytest.fixture()
def trabajador_validado(client, promotor):
    r = client.post("/api/trabajadores", json=datos_trabajador())
    assert r.status_code == 201
    cuerpo = r.json()
    v = client.post(f"/api/trabajadores/{cuerpo['id']}/validacion", json={"aprobar": True}, headers=promotor)
    assert v.status_code == 200
    return cuerpo
