"""Pruebas de integración de la API. Cada prueba referencia la historia de Jira (LIMP)."""

from tests.conftest import datos_trabajador


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_cabeceras_de_seguridad(client):
    r = client.get("/")
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'self'" in r.headers["Content-Security-Policy"]


# HU01 (LIMP-6)
def test_registro_exitoso_queda_pendiente(client):
    r = client.post("/api/trabajadores", json=datos_trabajador())
    assert r.status_code == 201
    assert r.json()["estado"] == "pendiente"


def test_registro_documento_duplicado(client):
    client.post("/api/trabajadores", json=datos_trabajador())
    r = client.post("/api/trabajadores", json=datos_trabajador())
    assert r.status_code == 409


def test_registro_de_menor_no_crea_cuenta_y_genera_alerta(client, promotor):
    r = client.post("/api/trabajadores", json=datos_trabajador(fecha_nacimiento="2012-03-01"))
    assert r.status_code == 422
    alertas = client.get("/api/alertas", headers=promotor).json()
    assert len(alertas) == 1 and alertas[0]["tipo"] == "menor"
    assert client.get("/api/trabajadores", headers=promotor).json() == []


def test_registro_rechaza_datos_invalidos(client):
    r = client.post("/api/trabajadores", json=datos_trabajador(celular="12345"))
    assert r.status_code == 422


# HU03 (LIMP-8) + protección de datos
def test_promotor_valida_y_documento_se_muestra_enmascarado(client, promotor):
    t = client.post("/api/trabajadores", json=datos_trabajador()).json()
    lista = client.get("/api/trabajadores?estado=pendiente", headers=promotor).json()
    assert lista[0]["documento_enmascarado"] == "*****912"
    r = client.post(f"/api/trabajadores/{t['id']}/validacion", json={"aprobar": True}, headers=promotor)
    assert r.json()["estado"] == "validado"


def test_rechazo_exige_motivo(client, promotor):
    t = client.post("/api/trabajadores", json=datos_trabajador()).json()
    r = client.post(f"/api/trabajadores/{t['id']}/validacion", json={"aprobar": False}, headers=promotor)
    assert r.status_code == 422


# HU16 (LIMP-21) – control de acceso por rol
def test_endpoints_internos_requieren_login(client):
    assert client.get("/api/panel").status_code == 401
    assert client.get("/api/alertas").status_code == 401


def test_login_con_password_incorrecta(client):
    r = client.post("/api/auth/login", json={"usuario": "promotor_test", "password": "incorrecta"})
    assert r.status_code == 401


def test_token_manipulado_es_rechazado(client):
    r = client.get("/api/panel", headers={"Authorization": "Bearer abc.def.ghi"})
    assert r.status_code == 401


def test_solo_admin_crea_usuarios(client, promotor, admin):
    nuevo = {"usuario": "nueva.promotora", "password": "Clave-Muy-Segura-1", "rol": "promotor"}
    assert client.post("/api/usuarios", json=nuevo, headers=promotor).status_code == 403
    assert client.post("/api/usuarios", json=nuevo, headers=admin).status_code == 201


# HU05 (LIMP-10)
def test_qr_solo_para_trabajador_validado(client, promotor):
    t = client.post("/api/trabajadores", json=datos_trabajador()).json()
    assert client.get(f"/api/qr/{t['qr_token']}.svg").status_code == 409
    client.post(f"/api/trabajadores/{t['id']}/validacion", json={"aprobar": True}, headers=promotor)
    r = client.get(f"/api/qr/{t['qr_token']}.svg")
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg+xml")


# HU06, HU07, HU08 (LIMP-11, 12, 13)
def test_propina_historial_y_calificacion(client, trabajador_validado):
    token = trabajador_validado["qr_token"]
    r = client.post("/api/propinas", json={"qr_token": token, "monto": 5, "billetera": "yape"})
    assert r.status_code == 201
    propina_id = r.json()["id"]
    client.post("/api/propinas", json={"qr_token": token, "monto": 2, "billetera": "plin"})
    h = client.get(f"/api/trabajadores/token/{token}/propinas").json()
    assert h["total_hoy"] == 7.0 and len(h["propinas"]) == 2
    assert client.post(f"/api/propinas/{propina_id}/calificacion", json={"estrellas": 5}).status_code == 200
    assert client.post(f"/api/propinas/{propina_id}/calificacion", json={"estrellas": 4}).status_code == 409


def test_propina_con_qr_invalido(client):
    r = client.post("/api/propinas", json={"qr_token": "codigo-alterado-123", "monto": 5, "billetera": "yape"})
    assert r.status_code == 404


def test_propina_monto_fuera_de_rango(client, trabajador_validado):
    datos = {"qr_token": trabajador_validado["qr_token"], "monto": 0, "billetera": "yape"}
    r = client.post("/api/propinas", json=datos)
    assert r.status_code == 422


# HU12, HU13 (LIMP-17, 18)
def test_reporte_de_menor_y_derivacion_a_demuna(client, promotor):
    r = client.post("/api/alertas", json={"cruce": "Av. Brasil / Av. Javier Prado", "descripcion": "Niño de ~10 años"})
    assert r.status_code == 201 and r.json()["codigo_seguimiento"].startswith("AL-")
    alerta = client.get("/api/alertas", headers=promotor).json()[0]
    assert alerta["estado"] == "nueva"
    d = client.post(f"/api/alertas/{alerta['id']}/derivar", json={"observaciones": "Derivado a DEMUNA Lince"},
                    headers=promotor)
    assert d.json()["estado"] == "derivada" and d.json()["derivada_por"] == "promotor_test"
    again = client.post(f"/api/alertas/{alerta['id']}/derivar", json={"observaciones": "otra vez"}, headers=promotor)
    assert again.status_code == 409


def test_reporte_sin_ubicacion_es_rechazado(client):
    assert client.post("/api/alertas", json={"cruce": ""}).status_code == 422


# HU15 (LIMP-20)
def test_panel_por_cruce(client, promotor, trabajador_validado):
    client.post("/api/propinas", json={"qr_token": trabajador_validado["qr_token"], "monto": 10, "billetera": "yape"})
    client.post("/api/alertas", json={"cruce": "Av. Javier Prado / Av. Arequipa"})
    p = client.get("/api/panel", headers=promotor).json()
    assert p["total_trabajadores"] == 1 and p["alertas_abiertas"] == 1 and p["propinas_total"] == 10.0
    assert p["por_cruce"][0]["cruce"] == "Av. Javier Prado / Av. Arequipa"
