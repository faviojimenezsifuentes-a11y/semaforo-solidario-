"""Configuración de la aplicación leída desde variables de entorno.

Ningún secreto se escribe en el código: SECRET_KEY y las credenciales iniciales
se inyectan como variables de entorno (en Render se configuran en el panel).
"""

import os
import secrets
from dataclasses import dataclass, field


def _default_secret() -> str:
    # En desarrollo se genera una clave aleatoria por arranque.
    # En producción SECRET_KEY debe definirse como variable de entorno.
    return secrets.token_urlsafe(48)


@dataclass
class Settings:
    database_url: str = field(
        default_factory=lambda: os.getenv("DATABASE_URL", "sqlite:///./semaforo.db")
    )
    secret_key: str = field(
        default_factory=lambda: os.getenv("SECRET_KEY") or _default_secret()
    )
    token_minutes: int = field(
        default_factory=lambda: int(os.getenv("TOKEN_MINUTES", "60"))
    )
    # Sin proveedor SMS contratado, el código OTP se muestra en pantalla (modo demostración).
    # En producción con SMS real se define OTP_DEMO=false.
    otp_demo: bool = field(
        default_factory=lambda: os.getenv("OTP_DEMO", "true").lower() == "true"
    )
    admin_user: str | None = field(default_factory=lambda: os.getenv("ADMIN_USER"))
    admin_password: str | None = field(
        default_factory=lambda: os.getenv("ADMIN_PASSWORD")
    )
    promotor_user: str | None = field(
        default_factory=lambda: os.getenv("PROMOTOR_USER")
    )
    promotor_password: str | None = field(
        default_factory=lambda: os.getenv("PROMOTOR_PASSWORD")
    )
