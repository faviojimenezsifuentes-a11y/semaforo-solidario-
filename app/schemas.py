"""Esquemas de entrada/salida (validación con Pydantic)."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TrabajadorIn(BaseModel):
    tipo_documento: Literal["DNI", "CE", "PTP"]
    numero_documento: str = Field(pattern=r"^[A-Za-z0-9]{8,12}$")
    nombres: str = Field(min_length=3, max_length=120)
    fecha_nacimiento: date
    celular: str = Field(pattern=r"^9\d{8}$")
    cruce: str = Field(min_length=3, max_length=120)
    horario: Literal["manana", "tarde", "noche"]


class TrabajadorRegistrado(BaseModel):
    id: int
    estado: str
    qr_token: str
    mensaje: str


class TrabajadorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tipo_documento: str
    documento_enmascarado: str
    nombres: str
    cruce: str
    horario: str
    estado: str
    creado_en: datetime


class Validacion(BaseModel):
    aprobar: bool
    motivo: str | None = Field(default=None, max_length=255)


class PropinaIn(BaseModel):
    qr_token: str = Field(min_length=10, max_length=64)
    monto: float = Field(gt=0, le=100)
    billetera: Literal["yape", "plin"]


class PropinaOut(BaseModel):
    id: int
    monto: float
    billetera: str
    creado_en: datetime
    mensaje: str | None = None


class CalificacionIn(BaseModel):
    estrellas: int = Field(ge=1, le=5)


class HistorialPropinas(BaseModel):
    trabajador: str
    total_hoy: float
    total_semana: float
    propinas: list[PropinaOut]


class AlertaIn(BaseModel):
    tipo: Literal["menor", "emergencia"] = "menor"
    cruce: str = Field(min_length=3, max_length=120)
    descripcion: str = Field(default="", max_length=500)


class AlertaCreada(BaseModel):
    codigo_seguimiento: str
    mensaje: str


class AlertaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tipo: str
    cruce: str
    descripcion: str
    estado: str
    codigo_seguimiento: str
    observaciones: str | None
    derivada_por: str | None
    creado_en: datetime


class Derivacion(BaseModel):
    observaciones: str = Field(min_length=5, max_length=500)


class LoginIn(BaseModel):
    usuario: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 - tipo de token OAuth2, no es una contraseña
    rol: str


class UsuarioIn(BaseModel):
    usuario: str = Field(pattern=r"^[a-z0-9_.]{4,60}$")
    password: str = Field(min_length=10, max_length=128)
    rol: Literal["promotor", "admin"]


class CruceResumen(BaseModel):
    cruce: str
    trabajadores: int
    validados: int
    alertas_abiertas: int
    propinas_total: float


class Panel(BaseModel):
    total_trabajadores: int
    pendientes_validacion: int
    alertas_abiertas: int
    propinas_total: float
    por_cruce: list[CruceResumen]
