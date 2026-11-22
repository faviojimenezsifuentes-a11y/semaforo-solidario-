"""Autenticación y autorización: contraseñas con PBKDF2 y tokens JWT con rol."""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import jwt

ITERACIONES = 240_000
ALGORITMO = "HS256"


def hash_password(password: str) -> str:
    sal = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), sal, ITERACIONES)
    return f"pbkdf2_sha256${ITERACIONES}${sal.hex()}${digest.hex()}"


def verificar_password(password: str, almacenado: str) -> bool:
    try:
        _, iteraciones, sal_hex, digest_hex = almacenado.split("$")
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(sal_hex), int(iteraciones)
    )
    return hmac.compare_digest(digest.hex(), digest_hex)


def crear_token(usuario: str, rol: str, clave: str, minutos: int) -> str:
    ahora = datetime.now(timezone.utc)
    payload = {"sub": usuario, "rol": rol, "iat": ahora, "exp": ahora + timedelta(minutes=minutos)}
    return jwt.encode(payload, clave, algorithm=ALGORITMO)


def leer_token(token: str, clave: str) -> dict:
    return jwt.decode(token, clave, algorithms=[ALGORITMO])
