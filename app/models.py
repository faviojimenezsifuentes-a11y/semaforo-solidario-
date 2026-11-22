"""Modelo de datos (SQLAlchemy 2.0)."""

from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text
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
