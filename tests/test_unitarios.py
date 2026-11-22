"""Pruebas unitarias de funciones puras."""

import secrets
from datetime import date

from app.main import edad, enmascarar, nuevo_codigo
from app.security import crear_token, hash_password, leer_token, verificar_password


def test_edad_considera_si_ya_cumplio_anios():
    assert edad(date(2008, 12, 31), hoy=date(2026, 11, 21)) == 17
    assert edad(date(2008, 1, 1), hoy=date(2026, 11, 21)) == 18


def test_enmascarar_documento_muestra_solo_tres_ultimos():
    assert enmascarar("45678912") == "*****912"


def test_codigo_de_seguimiento_tiene_formato():
    codigo = nuevo_codigo()
    assert codigo.startswith("AL-") and len(codigo) == 9


def test_password_se_guarda_con_hash_y_se_verifica():
    almacenado = hash_password("una-clave-segura")
    assert "una-clave-segura" not in almacenado
    assert verificar_password("una-clave-segura", almacenado)
    assert not verificar_password("otra-clave", almacenado)


def test_token_jwt_contiene_rol_y_se_valida_con_la_clave():
    clave = secrets.token_urlsafe(32)  # clave efímera: nunca escribir claves en el código
    token = crear_token("ana", "promotor", clave, 5)
    datos = leer_token(token, clave)
    assert datos["sub"] == "ana" and datos["rol"] == "promotor"
