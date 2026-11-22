"""Semáforo Solidario — API (FastAPI) + frontend estático.

Implementa el MVP de las épicas del backlog (Jira LIMP):
E1 registro/validación, E2 propina digital, E4 alertas de menores,
E5 panel y roles. Ver README.md para el mapeo historia -> endpoint.
"""

import io
import secrets
import string
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated

import segno
from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from jwt import PyJWTError
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app import schemas
from app.config import Settings
from app.models import Alerta, Base, Propina, Trabajador, Usuario
from app.security import crear_token, hash_password, leer_token, verificar_password

STATIC_DIR = Path(__file__).parent / "static"
bearer = HTTPBearer(auto_error=False)


def edad(nacimiento: date, hoy: date | None = None) -> int:
    hoy = hoy or date.today()
    return hoy.year - nacimiento.year - ((hoy.month, hoy.day) < (nacimiento.month, nacimiento.day))


def enmascarar(documento: str) -> str:
    """Protección de datos personales: solo se muestran los 3 últimos dígitos."""
    return "*" * (len(documento) - 3) + documento[-3:]


def nuevo_codigo() -> str:
    alfabeto = string.ascii_uppercase + string.digits
    return "AL-" + "".join(secrets.choice(alfabeto) for _ in range(6))


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
    engine = create_engine(settings.database_url, connect_args=connect_args)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)

    # Usuarios iniciales desde variables de entorno (nunca en el código).
    with SessionLocal() as db:
        for usuario, password, rol in (
            (settings.admin_user, settings.admin_password, "admin"),
            (settings.promotor_user, settings.promotor_password, "promotor"),
        ):
            if usuario and password and not db.scalar(select(Usuario).where(Usuario.usuario == usuario)):
                db.add(Usuario(usuario=usuario, password_hash=hash_password(password), rol=rol))
        db.commit()

    app = FastAPI(
        title="Semáforo Solidario API",
        version="1.0.0",
        description="Plataforma para formalizar y proteger a los limpiaparabrisas de los semáforos.",
    )

    @app.middleware("http")
    async def cabeceras_seguridad(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "geolocation=(self), camera=()"
        if not request.url.path.startswith(("/docs", "/openapi.json", "/redoc")):
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; img-src 'self' data:; style-src 'self'; "
                "script-src 'self'; frame-ancestors 'none'"
            )
        return response

    def get_db():
        with SessionLocal() as db:
            yield db

    Db = Annotated[Session, Depends(get_db)]

    def usuario_actual(
        db: Db, cred: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]
    ) -> Usuario:
        if cred is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Se requiere iniciar sesión")
        try:
            datos = leer_token(cred.credentials, settings.secret_key)
        except PyJWTError:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token inválido o vencido") from None
        usuario = db.scalar(select(Usuario).where(Usuario.usuario == datos.get("sub")))
        if usuario is None or not usuario.activo:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Usuario inactivo")
        return usuario

    def requiere_rol(*roles: str):
        def verificador(usuario: Annotated[Usuario, Depends(usuario_actual)]) -> Usuario:
            if usuario.rol not in roles:
                raise HTTPException(status.HTTP_403_FORBIDDEN, "No tiene permisos para esta acción")
            return usuario

        return verificador

    Staff = Annotated[Usuario, Depends(requiere_rol("promotor", "admin"))]
    Admin = Annotated[Usuario, Depends(requiere_rol("admin"))]

    def trabajador_por_token(db: Session, token: str) -> Trabajador:
        trabajador = db.scalar(select(Trabajador).where(Trabajador.qr_token == token))
        if trabajador is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "El código QR no es válido")
        return trabajador

    # ---------------- General ----------------
    @app.get("/health", tags=["general"])
    def health():
        return {"status": "ok", "servicio": "semaforo-solidario", "version": app.version}

    @app.get("/", include_in_schema=False)
    def inicio():
        return FileResponse(STATIC_DIR / "index.html")

    # ---------------- E1: Registro e identidad ----------------
    @app.post("/api/trabajadores", status_code=201, response_model=schemas.TrabajadorRegistrado, tags=["E1 Registro"])
    def registrar_trabajador(datos: schemas.TrabajadorIn, db: Db):
        """HU01 – Registrarse con documento de identidad."""
        if edad(datos.fecha_nacimiento) < 18:
            # Escenario 3: no se crea la cuenta y se alerta al promotor social.
            db.add(Alerta(tipo="menor", cruce=datos.cruce, codigo_seguimiento=nuevo_codigo(),
                          descripcion="Intento de registro de un menor de edad"))
            db.commit()
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                                "No se puede registrar a menores de edad. Un promotor social se comunicará.")
        if db.scalar(select(Trabajador).where(Trabajador.numero_documento == datos.numero_documento)):
            raise HTTPException(status.HTTP_409_CONFLICT, "El documento ya está registrado")
        trabajador = Trabajador(**datos.model_dump(), qr_token=secrets.token_urlsafe(24))
        db.add(trabajador)
        db.commit()
        return schemas.TrabajadorRegistrado(
            id=trabajador.id, estado=trabajador.estado, qr_token=trabajador.qr_token,
            mensaje="Registro recibido. Pendiente de validación por un promotor social.",
        )

    @app.get("/api/trabajadores", response_model=list[schemas.TrabajadorOut], tags=["E1 Registro"])
    def listar_trabajadores(db: Db, _: Staff, estado: str | None = None):
        consulta = select(Trabajador).order_by(Trabajador.creado_en.desc())
        if estado:
            consulta = consulta.where(Trabajador.estado == estado)
        return [
            schemas.TrabajadorOut(
                id=t.id, tipo_documento=t.tipo_documento, documento_enmascarado=enmascarar(t.numero_documento),
                nombres=t.nombres, cruce=t.cruce, horario=t.horario, estado=t.estado, creado_en=t.creado_en,
            )
            for t in db.scalars(consulta)
        ]

    @app.post("/api/trabajadores/{trabajador_id}/validacion", tags=["E1 Registro"])
    def validar_trabajador(trabajador_id: int, datos: schemas.Validacion, db: Db, _: Staff):
        """HU03 – El promotor aprueba o rechaza un registro."""
        trabajador = db.get(Trabajador, trabajador_id)
        if trabajador is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Trabajador no encontrado")
        if not datos.aprobar and not datos.motivo:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Debe indicar el motivo del rechazo")
        trabajador.estado = "validado" if datos.aprobar else "rechazado"
        trabajador.motivo_rechazo = None if datos.aprobar else datos.motivo
        db.commit()
        return {"id": trabajador.id, "estado": trabajador.estado}

    # ---------------- E2: Propina digital ----------------
    @app.get("/api/qr/{token}.svg", tags=["E2 Propina"])
    def qr_trabajador(token: str, request: Request, db: Db):
        """HU05 – QR personal (solo para trabajadores validados)."""
        trabajador = trabajador_por_token(db, token)
        if trabajador.estado != "validado":
            raise HTTPException(status.HTTP_409_CONFLICT, "Debe esperar la validación de su registro")
        url = f"{str(request.base_url).rstrip('/')}/?t={token}"
        buffer = io.BytesIO()
        segno.make(url, error="m").save(buffer, kind="svg", scale=6, border=2)
        return Response(buffer.getvalue(), media_type="image/svg+xml")

    @app.get("/api/qr/{token}", tags=["E2 Propina"])
    def datos_publicos(token: str, db: Db):
        trabajador = trabajador_por_token(db, token)
        if trabajador.estado != "validado":
            raise HTTPException(status.HTTP_404_NOT_FOUND, "El código QR no es válido")
        return {"nombre": trabajador.nombres.split()[0], "cruce": trabajador.cruce}

    @app.post("/api/propinas", status_code=201, response_model=schemas.PropinaOut, tags=["E2 Propina"])
    def dar_propina(datos: schemas.PropinaIn, db: Db):
        """HU06 – Propina con Yape/Plin (pasarela simulada en el MVP)."""
        trabajador = trabajador_por_token(db, datos.qr_token)
        if trabajador.estado != "validado":
            raise HTTPException(status.HTTP_404_NOT_FOUND, "El código QR no es válido")
        propina = Propina(trabajador_id=trabajador.id, monto_centimos=round(datos.monto * 100),
                          billetera=datos.billetera)
        db.add(propina)
        db.commit()
        return schemas.PropinaOut(id=propina.id, monto=propina.monto_centimos / 100, billetera=propina.billetera,
                                  creado_en=propina.creado_en, mensaje=f"¡Gracias! Se envió S/ {datos.monto:.2f}")

    @app.post("/api/propinas/{propina_id}/calificacion", tags=["E2 Propina"])
    def calificar(propina_id: int, datos: schemas.CalificacionIn, db: Db):
        """HU08 – Calificar el servicio (1 a 5 estrellas)."""
        propina = db.get(Propina, propina_id)
        if propina is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Propina no encontrada")
        if propina.calificacion is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, "Esta propina ya fue calificada")
        propina.calificacion = datos.estrellas
        db.commit()
        return {"id": propina.id, "calificacion": propina.calificacion}

    @app.get("/api/trabajadores/token/{token}/propinas", response_model=schemas.HistorialPropinas, tags=["E2 Propina"])
    def historial(token: str, db: Db):
        """HU07 – Historial de propinas con totales del día y de la semana."""
        trabajador = trabajador_por_token(db, token)
        ahora = datetime.now(timezone.utc)
        inicio_dia = ahora.replace(hour=0, minute=0, second=0, microsecond=0)
        inicio_semana = inicio_dia - timedelta(days=inicio_dia.weekday())
        propinas = db.scalars(
            select(Propina).where(Propina.trabajador_id == trabajador.id).order_by(Propina.creado_en.desc())
        ).all()

        def suma(desde: datetime) -> float:
            return sum(p.monto_centimos for p in propinas if p.creado_en.replace(tzinfo=timezone.utc) >= desde) / 100

        return schemas.HistorialPropinas(
            trabajador=trabajador.nombres, total_hoy=suma(inicio_dia), total_semana=suma(inicio_semana),
            propinas=[schemas.PropinaOut(id=p.id, monto=p.monto_centimos / 100, billetera=p.billetera,
                                         creado_en=p.creado_en) for p in propinas],
        )

    # ---------------- E4: Protección de menores y alertas ----------------
    @app.post("/api/alertas", status_code=201, response_model=schemas.AlertaCreada, tags=["E4 Alertas"])
    def reportar(datos: schemas.AlertaIn, db: Db):
        """HU12 – Reporte anónimo (no se guardan datos del conductor)."""
        alerta = Alerta(tipo=datos.tipo, cruce=datos.cruce, descripcion=datos.descripcion,
                        codigo_seguimiento=nuevo_codigo())
        db.add(alerta)
        db.commit()
        return schemas.AlertaCreada(codigo_seguimiento=alerta.codigo_seguimiento,
                                    mensaje="Reporte recibido. Un promotor social lo atenderá.")

    @app.get("/api/alertas", response_model=list[schemas.AlertaOut], tags=["E4 Alertas"])
    def listar_alertas(db: Db, _: Staff, estado: str | None = None):
        consulta = select(Alerta).order_by(Alerta.creado_en.desc())
        if estado:
            consulta = consulta.where(Alerta.estado == estado)
        return list(db.scalars(consulta))

    @app.post("/api/alertas/{alerta_id}/derivar", response_model=schemas.AlertaOut, tags=["E4 Alertas"])
    def derivar(alerta_id: int, datos: schemas.Derivacion, db: Db, usuario: Staff):
        """HU13 – Derivar la alerta a la DEMUNA, registrando responsable y fecha."""
        alerta = db.get(Alerta, alerta_id)
        if alerta is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Alerta no encontrada")
        if alerta.estado == "derivada":
            raise HTTPException(status.HTTP_409_CONFLICT, "La alerta ya fue derivada")
        alerta.estado = "derivada"
        alerta.observaciones = datos.observaciones
        alerta.derivada_por = usuario.usuario
        alerta.derivada_en = datetime.now(timezone.utc)
        db.commit()
        return alerta

    # ---------------- E5: Panel y seguridad ----------------
    @app.post("/api/auth/login", response_model=schemas.TokenOut, tags=["E5 Panel y seguridad"])
    def login(datos: schemas.LoginIn, db: Db):
        usuario = db.scalar(select(Usuario).where(Usuario.usuario == datos.usuario))
        if usuario is None or not usuario.activo or not verificar_password(datos.password, usuario.password_hash):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Usuario o contraseña incorrectos")
        token = crear_token(usuario.usuario, usuario.rol, settings.secret_key, settings.token_minutes)
        return schemas.TokenOut(access_token=token, rol=usuario.rol)

    @app.post("/api/usuarios", status_code=201, tags=["E5 Panel y seguridad"])
    def crear_usuario(datos: schemas.UsuarioIn, db: Db, _: Admin):
        """HU16 – El administrador crea usuarios internos con su rol."""
        if db.scalar(select(Usuario).where(Usuario.usuario == datos.usuario)):
            raise HTTPException(status.HTTP_409_CONFLICT, "El usuario ya existe")
        db.add(Usuario(usuario=datos.usuario, password_hash=hash_password(datos.password), rol=datos.rol))
        db.commit()
        return {"usuario": datos.usuario, "rol": datos.rol}

    @app.get("/api/panel", response_model=schemas.Panel, tags=["E5 Panel y seguridad"])
    def panel(db: Db, _: Staff):
        """HU15 – Indicadores por cruce para priorizar intervenciones."""
        cruces: dict[str, schemas.CruceResumen] = {}

        def fila(nombre: str) -> schemas.CruceResumen:
            return cruces.setdefault(nombre, schemas.CruceResumen(
                cruce=nombre, trabajadores=0, validados=0, alertas_abiertas=0, propinas_total=0))

        for t in db.scalars(select(Trabajador)):
            f = fila(t.cruce)
            f.trabajadores += 1
            f.validados += t.estado == "validado"
        for a in db.scalars(select(Alerta).where(Alerta.estado != "derivada")):
            fila(a.cruce).alertas_abiertas += 1
        for cruce, total in db.execute(
            select(Trabajador.cruce, func.sum(Propina.monto_centimos)).join(Propina).group_by(Trabajador.cruce)
        ):
            fila(cruce).propinas_total = (total or 0) / 100

        filas = sorted(cruces.values(), key=lambda c: (-c.alertas_abiertas, -c.trabajadores))
        return schemas.Panel(
            total_trabajadores=sum(c.trabajadores for c in filas),
            pendientes_validacion=db.scalar(
                select(func.count()).select_from(Trabajador).where(Trabajador.estado == "pendiente")) or 0,
            alertas_abiertas=sum(c.alertas_abiertas for c in filas),
            propinas_total=round(sum(c.propinas_total for c in filas), 2),
            por_cruce=filas,
        )

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


app = create_app()
