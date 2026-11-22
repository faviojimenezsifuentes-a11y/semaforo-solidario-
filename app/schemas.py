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
    distrito: str = ""
    lat: float | None = None
    lng: float | None = None
    trabajadores: int
    validados: int
    alertas_abiertas: int
    kits_entregados: int = 0
    propinas_total: float


class Panel(BaseModel):
    total_trabajadores: int
    pendientes_validacion: int
    alertas_abiertas: int
    emergencias_abiertas: int = 0
    kits_entregados: int = 0
    solicitudes_nuevas: int = 0
    propinas_total: float
    por_cruce: list[CruceResumen]
    distritos: list[str] = []


# ---------------- Ampliación ----------------
Celular = Field(pattern=r"^9\d{8}$")


class OtpSolicitud(BaseModel):
    celular: str = Celular


class OtpEnviado(BaseModel):
    mensaje: str
    codigo_demo: str | None = None  # solo en modo demostración (sin proveedor SMS)


class OtpVerificacion(BaseModel):
    celular: str = Celular
    codigo: str = Field(pattern=r"^\d{6}$")


class SesionTrabajador(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 - tipo de token OAuth2, no es una contraseña
    nombre: str
    estado: str


class CruceIn(BaseModel):
    cruce: str = Field(min_length=3, max_length=120)
    horario: Literal["manana", "tarde", "noche"]


class CruceAnterior(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    cruce: str
    horario: str
    hasta: datetime


class ContactoIn(BaseModel):
    nombre: str = Field(min_length=2, max_length=80)
    celular: str = Celular


class Perfil(BaseModel):
    nombres: str
    tipo_documento: str
    documento_enmascarado: str
    estado: str
    motivo_rechazo: str | None
    cruce: str
    horario: str
    qr_token: str | None
    calificacion_promedio: float | None
    contacto_emergencia: ContactoIn | None
    ultimo_kit: datetime | None
    historial_cruces: list[CruceAnterior]


class ProgramaOut(BaseModel):
    id: int
    nombre: str
    descripcion: str
    requisitos: str
    lugar: str
    solicitado: bool


class SolicitudOut(BaseModel):
    id: int
    trabajador: str
    celular: str
    cruce: str
    programa: str
    estado: str
    creado_en: datetime


class CapacitacionOut(BaseModel):
    id: int
    nombre: str
    fecha: datetime
    lugar: str
    cupos: int
    cupos_disponibles: int
    mi_estado: str | None


class InscripcionIn(BaseModel):
    lista_espera: bool = False


class EmpleoOut(BaseModel):
    id: int
    puesto: str
    empresa: str
    distrito: str
    sueldo: int
    postulado: bool


class Mensaje(BaseModel):
    mensaje: str
    estado: str | None = None


class EmergenciaIn(BaseModel):
    descripcion: str = Field(default="", max_length=300)


class EmergenciaOut(BaseModel):
    codigo_seguimiento: str
    mensaje: str
    avisados: list[str]


class KitIn(BaseModel):
    elementos: list[Literal["chaleco", "mascarilla", "guantes"]] = Field(min_length=1)
    motivo: str | None = Field(default=None, max_length=255)


class KitOut(BaseModel):
    id: int
    elementos: list[str]
    motivo: str | None
    registrado_por: str
    entregado_en: datetime


class UsuarioOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    usuario: str
    rol: str
    activo: bool


class UsuarioCambio(BaseModel):
    rol: Literal["promotor", "admin"] | None = None
    activo: bool | None = None


class AuditoriaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    actor: str
    accion: str
    detalle: str
    creado_en: datetime


class Estadisticas(BaseModel):
    trabajadores_validados: int
    cruces: int
    propinas_total: float
    alertas_atendidas: int
