"""Modelo de datos (SQLAlchemy 2.0)."""

from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def ahora() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Trabajador(Base):
    """Limpiaparabrisas registrado (Épica E1)."""

    __tablename__ = "trabajadores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tipo_documento: Mapped[str] = mapped_column(String(3))  # DNI | CE | PTP
    numero_documento: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    nombres: Mapped[str] = mapped_column(String(120))
    fecha_nacimiento: Mapped[date] = mapped_column(Date)
    celular: Mapped[str] = mapped_column(String(15))
    cruce: Mapped[str] = mapped_column(String(120))
    horario: Mapped[str] = mapped_column(String(10))  # manana | tarde | noche
    estado: Mapped[str] = mapped_column(String(12), default="pendiente")
    motivo_rechazo: Mapped[str | None] = mapped_column(String(255), nullable=True)
    qr_token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)

    propinas: Mapped[list["Propina"]] = relationship(back_populates="trabajador")


class Propina(Base):
    """Propina digital recibida (Épica E2). El pago con Yape/Plin se simula."""

    __tablename__ = "propinas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trabajador_id: Mapped[int] = mapped_column(ForeignKey("trabajadores.id"))
    monto_centimos: Mapped[int] = mapped_column(Integer)
    billetera: Mapped[str] = mapped_column(String(10))  # yape | plin
    calificacion: Mapped[int | None] = mapped_column(Integer, nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)

    trabajador: Mapped[Trabajador] = relationship(back_populates="propinas")


class Alerta(Base):
    """Alerta de menor trabajando o de emergencia (Épica E4)."""

    __tablename__ = "alertas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tipo: Mapped[str] = mapped_column(String(12))  # menor | emergencia
    cruce: Mapped[str] = mapped_column(String(120))
    descripcion: Mapped[str] = mapped_column(Text, default="")
    estado: Mapped[str] = mapped_column(String(12), default="nueva")
    codigo_seguimiento: Mapped[str] = mapped_column(String(12), unique=True)
    observaciones: Mapped[str | None] = mapped_column(Text, nullable=True)
    derivada_por: Mapped[str | None] = mapped_column(String(60), nullable=True)
    derivada_en: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)


class Usuario(Base):
    """Usuario interno con rol (promotor social o administrador) — HU16."""

    __tablename__ = "usuarios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    usuario: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    rol: Mapped[str] = mapped_column(String(10))  # promotor | admin
    activo: Mapped[bool] = mapped_column(default=True)


# ---------------- Ampliación: HU02, HU04, HU09, HU10, HU11, HU16 ----------------


class AccesoTrabajador(Base):
    """Código OTP de un solo uso para el ingreso del trabajador (HU02)."""

    __tablename__ = "accesos_trabajador"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trabajador_id: Mapped[int] = mapped_column(ForeignKey("trabajadores.id"), unique=True)
    codigo_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expira_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    intentos_fallidos: Mapped[int] = mapped_column(Integer, default=0)
    bloqueado_hasta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class HistorialCruce(Base):
    """Cruces y horarios anteriores del trabajador (HU04, escenario 2)."""

    __tablename__ = "historial_cruces"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trabajador_id: Mapped[int] = mapped_column(ForeignKey("trabajadores.id"))
    cruce: Mapped[str] = mapped_column(String(120))
    horario: Mapped[str] = mapped_column(String(10))
    hasta: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)


class ContactoEmergencia(Base):
    """Contacto que recibe el aviso del botón de emergencia (HU14)."""

    __tablename__ = "contactos_emergencia"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trabajador_id: Mapped[int] = mapped_column(ForeignKey("trabajadores.id"), unique=True)
    nombre: Mapped[str] = mapped_column(String(80))
    celular: Mapped[str] = mapped_column(String(15))


class Programa(Base):
    """Programa social del catálogo (HU09). documentos: tipos admitidos separados por coma."""

    __tablename__ = "programas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(120))
    descripcion: Mapped[str] = mapped_column(Text)
    requisitos: Mapped[str] = mapped_column(Text)
    lugar: Mapped[str] = mapped_column(String(160))
    documentos: Mapped[str] = mapped_column(String(20))
    edad_min: Mapped[int] = mapped_column(Integer, default=18)
    edad_max: Mapped[int] = mapped_column(Integer, default=120)


class SolicitudOrientacion(Base):
    """Pedido de orientación del trabajador sobre un programa (HU09, escenario 2)."""

    __tablename__ = "solicitudes_orientacion"
    __table_args__ = (UniqueConstraint("trabajador_id", "programa_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trabajador_id: Mapped[int] = mapped_column(ForeignKey("trabajadores.id"))
    programa_id: Mapped[int] = mapped_column(ForeignKey("programas.id"))
    estado: Mapped[str] = mapped_column(String(12), default="nueva")  # nueva | atendida
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)

    trabajador: Mapped[Trabajador] = relationship()
    programa: Mapped[Programa] = relationship()


class Capacitacion(Base):
    """Capacitación con cupos limitados (HU10)."""

    __tablename__ = "capacitaciones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(120))
    fecha: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lugar: Mapped[str] = mapped_column(String(160))
    cupos: Mapped[int] = mapped_column(Integer)


class Inscripcion(Base):
    """Inscripción a una capacitación: inscrito o en lista de espera (HU10)."""

    __tablename__ = "inscripciones"
    __table_args__ = (UniqueConstraint("trabajador_id", "capacitacion_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trabajador_id: Mapped[int] = mapped_column(ForeignKey("trabajadores.id"))
    capacitacion_id: Mapped[int] = mapped_column(ForeignKey("capacitaciones.id"))
    estado: Mapped[str] = mapped_column(String(10))  # inscrito | espera
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)


class Empleo(Base):
    """Oferta de empleo formal publicada por una empresa aliada (HU10)."""

    __tablename__ = "empleos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    puesto: Mapped[str] = mapped_column(String(120))
    empresa: Mapped[str] = mapped_column(String(120))
    distrito: Mapped[str] = mapped_column(String(80))
    sueldo: Mapped[int] = mapped_column(Integer)


class Postulacion(Base):
    """Postulación del trabajador a una oferta de empleo (HU10)."""

    __tablename__ = "postulaciones"
    __table_args__ = (UniqueConstraint("trabajador_id", "empleo_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trabajador_id: Mapped[int] = mapped_column(ForeignKey("trabajadores.id"))
    empleo_id: Mapped[int] = mapped_column(ForeignKey("empleos.id"))
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)


class EntregaKit(Base):
    """Entrega de kit de seguridad: chaleco, mascarilla, guantes (HU11)."""

    __tablename__ = "entregas_kit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trabajador_id: Mapped[int] = mapped_column(ForeignKey("trabajadores.id"))
    elementos: Mapped[str] = mapped_column(String(120))
    motivo: Mapped[str | None] = mapped_column(String(255), nullable=True)
    registrado_por: Mapped[str] = mapped_column(String(60))
    entregado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)


class Auditoria(Base):
    """Registro de quién cambió qué y cuándo (HU16, escenario 3)."""

    __tablename__ = "auditoria"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor: Mapped[str] = mapped_column(String(60))
    accion: Mapped[str] = mapped_column(String(40))
    detalle: Mapped[str] = mapped_column(String(255))
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)
