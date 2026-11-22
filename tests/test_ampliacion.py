"""Pruebas de las historias agregadas en la versión 2.0 (HU02, HU04, HU09, HU10, HU11, HU13, HU14, HU16)."""

import secrets
from datetime import datetime, timedelta, timezone

from tests.conftest import datos_trabajador, sesion_trabajador


def otp(client, celular="987654321"):
    return client.post("/api/auth/otp/solicitar", json={"celular": celular}).json()


def codigo_incorrecto(correcto: str) -> str:
    return f"{(int(correcto) + 1) % 1_000_000:06d}"


# HU02 (LIMP-7) – ingreso con celular y OTP
def test_otp_ingreso_correcto_da_acceso_al_perfil(client, trabajador_validado):
    cabecera = sesion_trabajador(client)
    perfil = client.get("/api/mi/perfil", headers=cabecera).json()
    assert perfil["estado"] == "validado" and perfil["documento_enmascarado"] == "*****912"
    assert perfil["qr_token"] == trabajador_validado["qr_token"]


def test_otp_es_de_un_solo_uso_y_se_rechaza_si_es_incorrecto(client, trabajador_validado):
    codigo = otp(client)["codigo_demo"]
    malo = client.post("/api/auth/otp/verificar", json={"celular": "987654321", "codigo": codigo_incorrecto(codigo)})
    assert malo.status_code == 401
    assert client.post("/api/auth/otp/verificar", json={"celular": "987654321", "codigo": codigo}).status_code == 200
    reuso = client.post("/api/auth/otp/verificar", json={"celular": "987654321", "codigo": codigo})
    assert reuso.status_code == 401


def test_otp_vencido_es_rechazado(client, trabajador_validado, monkeypatch):
    codigo = otp(client)["codigo_demo"]
    futuro = datetime.now(timezone.utc) + timedelta(minutes=6)

    class Reloj(datetime):
        @classmethod
        def now(cls, tz=None):
            return futuro

    monkeypatch.setattr("app.main.datetime", Reloj)
    r = client.post("/api/auth/otp/verificar", json={"celular": "987654321", "codigo": codigo})
    assert r.status_code == 401


def test_otp_bloquea_tras_5_intentos_fallidos(client, trabajador_validado):
    codigo = otp(client)["codigo_demo"]
    respuestas = [
        client.post("/api/auth/otp/verificar", json={"celular": "987654321", "codigo": codigo_incorrecto(codigo)})
        for _ in range(5)
    ]
    assert [r.status_code for r in respuestas] == [401, 401, 401, 401, 429]
    assert client.post("/api/auth/otp/solicitar", json={"celular": "987654321"}).status_code == 429


def test_otp_no_revela_celulares_no_registrados(client):
    r = otp(client, "911111111")
    assert r["codigo_demo"] is None and "Si el número está registrado" in r["mensaje"]


def test_token_de_trabajador_no_sirve_para_el_panel(client, yo):
    assert client.get("/api/panel", headers=yo).status_code == 401


def test_historial_de_propinas_requiere_sesion(client):
    assert client.get("/api/mi/propinas").status_code == 401


# HU04 (LIMP-9) – cruce y horario
def test_cambiar_cruce_conserva_historial(client, yo):
    r = client.put("/api/mi/cruce", json={"cruce": "Av. Brasil / Av. Javier Prado", "horario": "tarde"}, headers=yo)
    assert r.status_code == 200
    perfil = client.get("/api/mi/perfil", headers=yo).json()
    assert perfil["cruce"] == "Av. Brasil / Av. Javier Prado" and perfil["horario"] == "tarde"
    assert perfil["historial_cruces"][0]["cruce"] == "Av. Javier Prado / Av. Arequipa"


def test_trabajador_pendiente_no_puede_cambiar_cruce(client):
    client.post("/api/trabajadores", json=datos_trabajador())
    cabecera = sesion_trabajador(client)
    r = client.put("/api/mi/cruce", json={"cruce": "Otro cruce", "horario": "noche"}, headers=cabecera)
    assert r.status_code == 409


# HU09 (LIMP-14) – programas sociales según perfil
def test_programas_se_filtran_por_documento_y_edad(client, yo):
    nombres = [p["nombre"] for p in client.get("/api/mi/programas", headers=yo).json()]
    assert "SIS – Seguro Integral de Salud" in nombres  # DNI
    assert "Orientación legal y regularización migratoria" not in nombres  # solo CE/PTP
    assert "Capacitación laboral juvenil" in nombres  # nacido en 1999: menos de 30 años


def test_migrante_con_ptp_ve_orientacion_migratoria(client, promotor):
    t = client.post("/api/trabajadores", json=datos_trabajador(
        tipo_documento="PTP", numero_documento="PTP1234567", celular="955555555",
        fecha_nacimiento="1980-01-01")).json()
    client.post(f"/api/trabajadores/{t['id']}/validacion", json={"aprobar": True}, headers=promotor)
    nombres = [p["nombre"] for p in client.get("/api/mi/programas", headers=sesion_trabajador(client, "955555555"))
               .json()]
    assert "Orientación legal y regularización migratoria" in nombres
    assert "SIS – Seguro Integral de Salud" not in nombres
    assert "Capacitación laboral juvenil" not in nombres


def test_solicitud_de_orientacion_llega_al_promotor(client, yo, promotor):
    programa = client.get("/api/mi/programas", headers=yo).json()[0]
    url = f"/api/mi/programas/{programa['id']}/solicitud"
    assert client.post(url, headers=yo).status_code == 201
    assert client.post(url, headers=yo).status_code == 409
    solicitudes = client.get("/api/solicitudes", headers=promotor).json()
    assert solicitudes[0]["programa"] == programa["nombre"] and solicitudes[0]["estado"] == "nueva"
    assert client.get("/api/panel", headers=promotor).json()["solicitudes_nuevas"] == 1
    r = client.post(f"/api/solicitudes/{solicitudes[0]['id']}/atender", headers=promotor)
    assert r.json()["estado"] == "atendida"


# HU10 (LIMP-15) – capacitaciones y empleo
def test_inscripcion_reserva_cupo_y_luego_lista_de_espera(client, yo, promotor):
    capacitacion = client.get("/api/mi/capacitaciones", headers=yo).json()[0]
    url = f"/api/mi/capacitaciones/{capacitacion['id']}/inscripcion"
    r = client.post(url, json={}, headers=yo)
    assert r.status_code == 201 and r.json()["estado"] == "inscrito"
    assert client.post(url, json={}, headers=yo).status_code == 409
    actual = client.get("/api/mi/capacitaciones", headers=yo).json()[0]
    assert actual["mi_estado"] == "inscrito" and actual["cupos_disponibles"] == capacitacion["cupos"] - 1


def test_capacitacion_sin_cupos_ofrece_lista_de_espera(client, yo, promotor):
    capacitacion = client.get("/api/mi/capacitaciones", headers=yo).json()[1]
    # Se llenan los cupos con otros trabajadores validados
    for i in range(capacitacion["cupos"]):
        t = client.post("/api/trabajadores", json=datos_trabajador(
            numero_documento=f"7000{i:04d}", celular=f"9100{i:05d}")).json()
        client.post(f"/api/trabajadores/{t['id']}/validacion", json={"aprobar": True}, headers=promotor)
        otro = sesion_trabajador(client, f"9100{i:05d}")
        client.post(f"/api/mi/capacitaciones/{capacitacion['id']}/inscripcion", json={}, headers=otro)
    url = f"/api/mi/capacitaciones/{capacitacion['id']}/inscripcion"
    assert client.post(url, json={}, headers=yo).status_code == 409
    r = client.post(url, json={"lista_espera": True}, headers=yo)
    assert r.status_code == 201 and r.json()["estado"] == "espera"


def test_postular_a_empleo(client, yo):
    empleo = client.get("/api/mi/empleos", headers=yo).json()[0]
    url = f"/api/mi/empleos/{empleo['id']}/postulacion"
    assert client.post(url, headers=yo).status_code == 201
    assert client.post(url, headers=yo).status_code == 409
    assert client.get("/api/mi/empleos", headers=yo).json()[0]["postulado"] is True


# HU11 (LIMP-16) – kits de seguridad
def test_kit_duplicado_exige_motivo(client, promotor, trabajador_validado):
    url = f"/api/trabajadores/{trabajador_validado['id']}/kits"
    assert client.post(url, json={"elementos": ["chaleco", "guantes"]}, headers=promotor).status_code == 201
    assert client.post(url, json={"elementos": ["chaleco"]}, headers=promotor).status_code == 409
    r = client.post(url, json={"elementos": ["chaleco"], "motivo": "Chaleco robado"}, headers=promotor)
    assert r.status_code == 201
    assert len(client.get(url, headers=promotor).json()) == 2
    assert client.get("/api/panel", headers=promotor).json()["kits_entregados"] == 2


# HU13 (LIMP-18) escenario 3 – alerta vencida
def test_alerta_sin_atender_48h_se_marca_vencida(client, promotor, monkeypatch):
    client.post("/api/alertas", json={"cruce": "Av. Brasil / Av. Javier Prado"})
    futuro = datetime.now(timezone.utc) + timedelta(hours=49)

    class Reloj(datetime):
        @classmethod
        def now(cls, tz=None):
            return futuro

    monkeypatch.setattr("app.main.datetime", Reloj)
    alerta = client.get("/api/alertas", headers=promotor).json()[0]
    assert alerta["estado"] == "vencida"


# HU14 (LIMP-19) – botón de emergencia
def test_emergencia_avisa_al_promotor_y_al_contacto(client, yo, promotor):
    client.put("/api/mi/contacto-emergencia", json={"nombre": "María", "celular": "966666666"}, headers=yo)
    r = client.post("/api/mi/emergencia", json={}, headers=yo)
    assert r.status_code == 201 and "María (SMS)" in r.json()["avisados"]
    alerta = client.get("/api/alertas", headers=promotor).json()[0]
    assert alerta["tipo"] == "emergencia" and alerta["cruce"] == "Av. Javier Prado / Av. Arequipa"
    assert client.get("/api/panel", headers=promotor).json()["emergencias_abiertas"] == 1


# HU16 (LIMP-21) – usuarios, desactivación y auditoría
def test_desactivar_usuario_cierra_su_sesion_y_queda_auditado(client, admin):
    clave = secrets.token_urlsafe(16)
    client.post("/api/usuarios", json={"usuario": "ana.promotora", "password": clave, "rol": "promotor"},
                headers=admin)
    r = client.post("/api/auth/login", json={"usuario": "ana.promotora", "password": clave})
    sesion_ana = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.get("/api/panel", headers=sesion_ana).status_code == 200
    ana = next(u for u in client.get("/api/usuarios", headers=admin).json() if u["usuario"] == "ana.promotora")
    assert client.patch(f"/api/usuarios/{ana['id']}", json={"activo": False}, headers=admin).status_code == 200
    assert client.get("/api/panel", headers=sesion_ana).status_code == 401
    acciones = [a["accion"] for a in client.get("/api/auditoria", headers=admin).json()]
    assert "desactivar" in acciones and "crear_usuario" in acciones


def test_admin_no_puede_desactivarse_a_si_mismo(client, admin):
    yo_admin = next(u for u in client.get("/api/usuarios", headers=admin).json() if u["rol"] == "admin")
    r = client.patch(f"/api/usuarios/{yo_admin['id']}", json={"activo": False}, headers=admin)
    assert r.status_code == 409


def test_promotor_no_gestiona_usuarios(client, promotor):
    assert client.get("/api/usuarios", headers=promotor).status_code == 403


def test_estadisticas_publicas_sin_datos_personales(client, trabajador_validado):
    e = client.get("/api/estadisticas").json()
    assert e == {"trabajadores_validados": 1, "cruces": 1, "propinas_total": 0.0, "alertas_atendidas": 0}
