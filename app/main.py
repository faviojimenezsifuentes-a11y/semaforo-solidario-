"""Semáforo Solidario — API (FastAPI) + frontend estático.

Implementa las 5 épicas del backlog (Jira LIMP):
E1 registro, acceso OTP y cruce; E2 propina digital; E3 protección social y
empleabilidad; E4 alertas de menores y emergencias; E5 panel, roles y auditoría.
Ver README.md para el mapeo historia -> endpoint.
"""

import hashlib
import hmac
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
from app.catalogo import cargar_catalogo
from app.config import Settings
from app.models import (
    AccesoTrabajador,
    Alerta,
    Auditoria,
    Base,
    Capacitacion,
    ContactoEmergencia,
    Empleo,
    EntregaKit,
    HistorialCruce,
    Inscripcion,
    Postulacion,
    Programa,
    Propina,
    SolicitudOrientacion,
    Trabajador,
    Usuario,
)
from app.security import crear_token, hash_password, leer_token, verificar_password

STATIC_DIR = Path(__file__).parent / "static"
bearer = HTTPBearer(auto_error=False)

OTP_MINUTOS = 5          # HU02: el código vence a los 5 minutos
OTP_MAX_INTENTOS = 5     # HU02: 5 intentos fallidos seguidos...
BLOQUEO_MINUTOS = 15     # ...bloquean el acceso 15 minutos
DIAS_ENTRE_KITS = 90     # HU11: advertencia si recibió un kit hace menos de 3 meses
HORAS_ALERTA = 48        # HU13: una alerta sin atender por 48 h se marca como vencida
PREFIJO_TRABAJADOR = "trabajador:"


def edad(nacimiento: date, hoy: date | None = None) -> int:
    hoy = hoy or date.today()
    return hoy.year - nacimiento.year - ((hoy.month, hoy.day) < (nacimiento.month, nacimiento.day))


def enmascarar(documento: str) -> str:
    """Protección de datos personales: solo se muestran los 3 últimos dígitos."""
    return "*" * (len(documento) - 3) + documento[-3:]


def nuevo_codigo() -> str:
    alfabeto = string.ascii_uppercase + string.digits
    return "AL-" + "".join(secrets.choice(alfabeto) for _ in range(6))


def utc(momento: datetime | None) -> datetime | None:
    """SQLite devuelve fechas sin zona horaria: se interpretan como UTC."""
    if momento is not None and momento.tzinfo is None:
        return momento.replace(tzinfo=timezone.utc)
    return momento


def hash_otp(codigo: str, clave: str) -> str:
    """El OTP nunca se guarda en claro: HMAC-SHA256 con la clave del servidor."""
    return hmac.new(clave.encode(), codigo.encode(), hashlib.sha256).hexdigest()


def programa_aplica(programa: Programa, tipo_documento: str, anios: int) -> bool:
    """HU09: el programa aplica según documento (nacionalidad) y edad."""
    return tipo_documento in programa.documentos.split(",") and programa.edad_min <= anios <= programa.edad_max


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
        cargar_catalogo(db)

    app = FastAPI(
        title="Semáforo Solidario API",
        version="2.0.0",
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

    def trabajador_actual(
        db: Db, cred: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]
    ) -> Trabajador:
        """Sesión del trabajador (token JWT emitido tras verificar el OTP)."""
        if cred is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Inicia sesión con tu celular")
        try:
            datos = leer_token(cred.credentials, settings.secret_key)
        except PyJWTError:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Tu sesión venció, vuelve a ingresar") from None
        sub = str(datos.get("sub", ""))
        if datos.get("rol") != "trabajador" or not sub.startswith(PREFIJO_TRABAJADOR):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "No tiene permisos para esta acción")
        trabajador = db.get(Trabajador, int(sub.removeprefix(PREFIJO_TRABAJADOR)))
        if trabajador is None or trabajador.estado == "rechazado":
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Cuenta no disponible")
        return trabajador

    Yo = Annotated[Trabajador, Depends(trabajador_actual)]

    def solo_validado(trabajador: Yo) -> Trabajador:
        if trabajador.estado != "validado":
            raise HTTPException(status.HTTP_409_CONFLICT, "Debes esperar la validación de tu registro")
        return trabajador

    YoValidado = Annotated[Trabajador, Depends(solo_validado)]

    def auditar(db: Session, actor: str, accion: str, detalle: str) -> None:
        db.add(Auditoria(actor=actor, accion=accion, detalle=detalle))

    def vencer_alertas(db: Session) -> None:
        """HU13 escenario 3: alertas nuevas sin atender por más de 48 h pasan a 'vencida'."""
        limite = datetime.now(timezone.utc) - timedelta(hours=HORAS_ALERTA)
        for alerta in db.scalars(select(Alerta).where(Alerta.estado == "nueva")):
            if utc(alerta.creado_en) < limite:
                alerta.estado = "vencida"
        db.commit()

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

    @app.get("/api/mi/propinas", response_model=schemas.HistorialPropinas, tags=["E2 Propina"])
    def historial(trabajador: Yo, db: Db):
        """HU07 – Historial de propinas con totales del día y de la semana (solo el propio trabajador)."""
        ahora = datetime.now(timezone.utc)
        inicio_dia = ahora.replace(hour=0, minute=0, second=0, microsecond=0)
        inicio_semana = inicio_dia - timedelta(days=inicio_dia.weekday())
        propinas = db.scalars(
            select(Propina).where(Propina.trabajador_id == trabajador.id).order_by(Propina.creado_en.desc())
        ).all()

        def suma(desde: datetime) -> float:
            return sum(p.monto_centimos for p in propinas if utc(p.creado_en) >= desde) / 100

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
        vencer_alertas(db)
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
    def crear_usuario(datos: schemas.UsuarioIn, db: Db, admin: Admin):
        """HU16 – El administrador crea usuarios internos con su rol."""
        if db.scalar(select(Usuario).where(Usuario.usuario == datos.usuario)):
            raise HTTPException(status.HTTP_409_CONFLICT, "El usuario ya existe")
        db.add(Usuario(usuario=datos.usuario, password_hash=hash_password(datos.password), rol=datos.rol))
        auditar(db, admin.usuario, "crear_usuario", f"{datos.usuario} con rol {datos.rol}")
        db.commit()
        return {"usuario": datos.usuario, "rol": datos.rol}

    @app.get("/api/panel", response_model=schemas.Panel, tags=["E5 Panel y seguridad"])
    def panel(db: Db, _: Staff):
        """HU15 – Indicadores por cruce para priorizar intervenciones."""
        cruces: dict[str, schemas.CruceResumen] = {}

        def fila(nombre: str) -> schemas.CruceResumen:
            return cruces.setdefault(nombre, schemas.CruceResumen(
                cruce=nombre, trabajadores=0, validados=0, alertas_abiertas=0, kits_entregados=0, propinas_total=0))

        vencer_alertas(db)

        for t in db.scalars(select(Trabajador)):
            f = fila(t.cruce)
            f.trabajadores += 1
            f.validados += t.estado == "validado"
        abiertas = list(db.scalars(select(Alerta).where(Alerta.estado != "derivada")))
        for a in abiertas:
            fila(a.cruce).alertas_abiertas += 1
        for cruce, total in db.execute(
            select(Trabajador.cruce, func.count(EntregaKit.id)).join(EntregaKit).group_by(Trabajador.cruce)
        ):
            fila(cruce).kits_entregados = total
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
            emergencias_abiertas=sum(a.tipo == "emergencia" for a in abiertas),
            kits_entregados=sum(c.kits_entregados for c in filas),
            solicitudes_nuevas=db.scalar(
                select(func.count()).select_from(SolicitudOrientacion).where(SolicitudOrientacion.estado == "nueva"))
            or 0,
            propinas_total=round(sum(c.propinas_total for c in filas), 2),
            por_cruce=filas,
        )

    # ---------------- Público ----------------
    @app.get("/api/estadisticas", response_model=schemas.Estadisticas, tags=["general"])
    def estadisticas(db: Db):
        """Cifras agregadas y anónimas para la portada (sin datos personales)."""
        validados = db.scalar(select(func.count()).select_from(Trabajador).where(Trabajador.estado == "validado"))
        cruces = db.scalar(select(func.count(func.distinct(Trabajador.cruce))).where(Trabajador.estado == "validado"))
        total = db.scalar(select(func.sum(Propina.monto_centimos)))
        atendidas = db.scalar(select(func.count()).select_from(Alerta).where(Alerta.estado == "derivada"))
        return schemas.Estadisticas(trabajadores_validados=validados or 0, cruces=cruces or 0,
                                    propinas_total=(total or 0) / 100, alertas_atendidas=atendidas or 0)

    # ---------------- E1: acceso del trabajador con OTP (HU02) ----------------
    def trabajador_por_celular(db: Session, celular: str) -> Trabajador | None:
        return db.scalar(select(Trabajador).where(Trabajador.celular == celular, Trabajador.estado != "rechazado")
                         .order_by(Trabajador.creado_en.desc()))

    def acceso_de(db: Session, trabajador: Trabajador) -> AccesoTrabajador:
        acceso = db.scalar(select(AccesoTrabajador).where(AccesoTrabajador.trabajador_id == trabajador.id))
        if acceso is None:
            acceso = AccesoTrabajador(trabajador_id=trabajador.id, intentos_fallidos=0)
            db.add(acceso)
        return acceso

    def verificar_bloqueo(acceso: AccesoTrabajador, ahora: datetime) -> None:
        if acceso.bloqueado_hasta and utc(acceso.bloqueado_hasta) > ahora:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                                f"Acceso bloqueado por {BLOQUEO_MINUTOS} minutos por intentos fallidos")

    @app.post("/api/auth/otp/solicitar", response_model=schemas.OtpEnviado, tags=["E1 Registro"])
    def solicitar_otp(datos: schemas.OtpSolicitud, db: Db):
        """HU02 – Envía un código de 6 dígitos por SMS (vence en 5 minutos)."""
        mensaje = "Si el número está registrado, te enviamos un código por SMS."
        trabajador = trabajador_por_celular(db, datos.celular)
        if trabajador is None:  # misma respuesta: no se revela qué celulares existen
            return schemas.OtpEnviado(mensaje=mensaje)
        ahora = datetime.now(timezone.utc)
        acceso = acceso_de(db, trabajador)
        verificar_bloqueo(acceso, ahora)
        codigo = f"{secrets.randbelow(1_000_000):06d}"
        acceso.codigo_hash = hash_otp(codigo, settings.secret_key)
        acceso.expira_en = ahora + timedelta(minutes=OTP_MINUTOS)
        db.commit()
        return schemas.OtpEnviado(mensaje=mensaje, codigo_demo=codigo if settings.otp_demo else None)

    @app.post("/api/auth/otp/verificar", response_model=schemas.SesionTrabajador, tags=["E1 Registro"])
    def verificar_otp(datos: schemas.OtpVerificacion, db: Db):
        """HU02 – Valida el código; 5 fallos seguidos bloquean el acceso 15 minutos."""
        trabajador = trabajador_por_celular(db, datos.celular)
        if trabajador is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Código incorrecto o vencido")
        ahora = datetime.now(timezone.utc)
        acceso = acceso_de(db, trabajador)
        verificar_bloqueo(acceso, ahora)
        correcto = (
            acceso.codigo_hash is not None
            and acceso.expira_en is not None
            and utc(acceso.expira_en) >= ahora
            and hmac.compare_digest(acceso.codigo_hash, hash_otp(datos.codigo, settings.secret_key))
        )
        if not correcto:
            acceso.intentos_fallidos += 1
            if acceso.intentos_fallidos >= OTP_MAX_INTENTOS:
                acceso.intentos_fallidos = 0
                acceso.codigo_hash = None
                acceso.bloqueado_hasta = ahora + timedelta(minutes=BLOQUEO_MINUTOS)
                db.commit()
                raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                                    f"Acceso bloqueado por {BLOQUEO_MINUTOS} minutos por intentos fallidos")
            db.commit()
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Código incorrecto o vencido. Puedes pedir uno nuevo.")
        acceso.codigo_hash = None  # un solo uso
        acceso.intentos_fallidos = 0
        acceso.bloqueado_hasta = None
        db.commit()
        token = crear_token(f"{PREFIJO_TRABAJADOR}{trabajador.id}", "trabajador", settings.secret_key,
                            settings.token_minutes)
        return schemas.SesionTrabajador(access_token=token, nombre=trabajador.nombres.split()[0],
                                        estado=trabajador.estado)

    # ---------------- E1: perfil y cruce del trabajador (HU04) ----------------
    @app.get("/api/mi/perfil", response_model=schemas.Perfil, tags=["E1 Registro"])
    def mi_perfil(trabajador: Yo, db: Db):
        promedio = db.scalar(select(func.avg(Propina.calificacion)).where(
            Propina.trabajador_id == trabajador.id, Propina.calificacion.is_not(None)))
        contacto = db.scalar(select(ContactoEmergencia).where(ContactoEmergencia.trabajador_id == trabajador.id))
        ultimo_kit = db.scalar(select(func.max(EntregaKit.entregado_en)).where(
            EntregaKit.trabajador_id == trabajador.id))
        historial_cruces = db.scalars(select(HistorialCruce).where(HistorialCruce.trabajador_id == trabajador.id)
                                      .order_by(HistorialCruce.hasta.desc())).all()
        return schemas.Perfil(
            nombres=trabajador.nombres, tipo_documento=trabajador.tipo_documento,
            documento_enmascarado=enmascarar(trabajador.numero_documento), estado=trabajador.estado,
            motivo_rechazo=trabajador.motivo_rechazo, cruce=trabajador.cruce, horario=trabajador.horario,
            qr_token=trabajador.qr_token if trabajador.estado == "validado" else None,
            calificacion_promedio=round(promedio, 1) if promedio else None,
            contacto_emergencia=schemas.ContactoIn(nombre=contacto.nombre, celular=contacto.celular)
            if contacto else None,
            ultimo_kit=ultimo_kit, historial_cruces=list(historial_cruces),
        )

    @app.put("/api/mi/cruce", response_model=schemas.Mensaje, tags=["E1 Registro"])
    def cambiar_cruce(datos: schemas.CruceIn, trabajador: YoValidado, db: Db):
        """HU04 – Registrar o cambiar el cruce y horario, conservando el historial."""
        if (datos.cruce, datos.horario) == (trabajador.cruce, trabajador.horario):
            return schemas.Mensaje(mensaje="Tu cruce y horario no cambiaron.")
        db.add(HistorialCruce(trabajador_id=trabajador.id, cruce=trabajador.cruce, horario=trabajador.horario))
        trabajador.cruce, trabajador.horario = datos.cruce, datos.horario
        db.commit()
        return schemas.Mensaje(mensaje="Actualizamos tu cruce y horario.")

    @app.put("/api/mi/contacto-emergencia", response_model=schemas.Mensaje, tags=["E4 Alertas"])
    def guardar_contacto(datos: schemas.ContactoIn, trabajador: Yo, db: Db):
        contacto = db.scalar(select(ContactoEmergencia).where(ContactoEmergencia.trabajador_id == trabajador.id))
        if contacto is None:
            contacto = ContactoEmergencia(trabajador_id=trabajador.id)
            db.add(contacto)
        contacto.nombre, contacto.celular = datos.nombre, datos.celular
        db.commit()
        return schemas.Mensaje(mensaje="Contacto de emergencia guardado.")

    # ---------------- E3: protección social y empleabilidad ----------------
    @app.get("/api/mi/programas", response_model=list[schemas.ProgramaOut], tags=["E3 Protección social"])
    def mis_programas(trabajador: YoValidado, db: Db):
        """HU09 – Solo los programas para los que califica (documento y edad)."""
        anios = edad(trabajador.fecha_nacimiento)
        pedidos = set(db.scalars(select(SolicitudOrientacion.programa_id).where(
            SolicitudOrientacion.trabajador_id == trabajador.id)))
        return [
            schemas.ProgramaOut(id=p.id, nombre=p.nombre, descripcion=p.descripcion, requisitos=p.requisitos,
                                lugar=p.lugar, solicitado=p.id in pedidos)
            for p in db.scalars(select(Programa).order_by(Programa.id))
            if programa_aplica(p, trabajador.tipo_documento, anios)
        ]

    @app.post("/api/mi/programas/{programa_id}/solicitud", status_code=201, response_model=schemas.Mensaje,
              tags=["E3 Protección social"])
    def solicitar_orientacion(programa_id: int, trabajador: YoValidado, db: Db):
        """HU09 – 'Quiero inscribirme': crea una solicitud de orientación para el promotor."""
        programa = db.get(Programa, programa_id)
        if programa is None or not programa_aplica(programa, trabajador.tipo_documento,
                                                   edad(trabajador.fecha_nacimiento)):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Programa no disponible para tu perfil")
        if db.scalar(select(SolicitudOrientacion).where(SolicitudOrientacion.trabajador_id == trabajador.id,
                                                        SolicitudOrientacion.programa_id == programa_id)):
            raise HTTPException(status.HTTP_409_CONFLICT, "Ya pediste orientación para este programa")
        db.add(SolicitudOrientacion(trabajador_id=trabajador.id, programa_id=programa_id))
        db.commit()
        return schemas.Mensaje(mensaje="Listo. Un promotor social te contactará para ayudarte con la inscripción.")

    @app.get("/api/solicitudes", response_model=list[schemas.SolicitudOut], tags=["E3 Protección social"])
    def listar_solicitudes(db: Db, _: Staff):
        return [
            schemas.SolicitudOut(id=s.id, trabajador=s.trabajador.nombres, celular=s.trabajador.celular,
                                 cruce=s.trabajador.cruce, programa=s.programa.nombre, estado=s.estado,
                                 creado_en=s.creado_en)
            for s in db.scalars(select(SolicitudOrientacion).order_by(SolicitudOrientacion.creado_en.desc()))
        ]

    @app.post("/api/solicitudes/{solicitud_id}/atender", response_model=schemas.Mensaje,
              tags=["E3 Protección social"])
    def atender_solicitud(solicitud_id: int, db: Db, usuario: Staff):
        solicitud = db.get(SolicitudOrientacion, solicitud_id)
        if solicitud is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Solicitud no encontrada")
        solicitud.estado = "atendida"
        auditar(db, usuario.usuario, "atender_solicitud", f"solicitud {solicitud_id}")
        db.commit()
        return schemas.Mensaje(mensaje="Solicitud marcada como atendida", estado="atendida")

    @app.get("/api/mi/capacitaciones", response_model=list[schemas.CapacitacionOut], tags=["E3 Protección social"])
    def mis_capacitaciones(trabajador: YoValidado, db: Db):
        mias = {i.capacitacion_id: i.estado for i in db.scalars(
            select(Inscripcion).where(Inscripcion.trabajador_id == trabajador.id))}
        ocupados = dict(db.execute(select(Inscripcion.capacitacion_id, func.count()).where(
            Inscripcion.estado == "inscrito").group_by(Inscripcion.capacitacion_id)).all())
        return [
            schemas.CapacitacionOut(id=c.id, nombre=c.nombre, fecha=c.fecha, lugar=c.lugar, cupos=c.cupos,
                                    cupos_disponibles=max(c.cupos - ocupados.get(c.id, 0), 0),
                                    mi_estado=mias.get(c.id))
            for c in db.scalars(select(Capacitacion).order_by(Capacitacion.fecha))
        ]

    @app.post("/api/mi/capacitaciones/{capacitacion_id}/inscripcion", status_code=201,
              response_model=schemas.Mensaje, tags=["E3 Protección social"])
    def inscribirse(capacitacion_id: int, datos: schemas.InscripcionIn, trabajador: YoValidado, db: Db):
        """HU10 – Reserva un cupo o, si no hay, ofrece la lista de espera."""
        capacitacion = db.get(Capacitacion, capacitacion_id)
        if capacitacion is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Capacitación no encontrada")
        if db.scalar(select(Inscripcion).where(Inscripcion.trabajador_id == trabajador.id,
                                               Inscripcion.capacitacion_id == capacitacion_id)):
            raise HTTPException(status.HTTP_409_CONFLICT, "Ya estás inscrito en esta capacitación")
        ocupados = db.scalar(select(func.count()).select_from(Inscripcion).where(
            Inscripcion.capacitacion_id == capacitacion_id, Inscripcion.estado == "inscrito")) or 0
        if ocupados < capacitacion.cupos:
            db.add(Inscripcion(trabajador_id=trabajador.id, capacitacion_id=capacitacion_id, estado="inscrito"))
            db.commit()
            fecha = utc(capacitacion.fecha).astimezone(timezone(timedelta(hours=-5)))
            return schemas.Mensaje(
                estado="inscrito",
                mensaje=f"Cupo reservado. Te enviamos por SMS los datos: {fecha:%d/%m %H:%M} en {capacitacion.lugar}.")
        if not datos.lista_espera:
            raise HTTPException(status.HTTP_409_CONFLICT, "No hay cupos. ¿Quieres quedar en lista de espera?")
        db.add(Inscripcion(trabajador_id=trabajador.id, capacitacion_id=capacitacion_id, estado="espera"))
        db.commit()
        return schemas.Mensaje(estado="espera",
                               mensaje="Quedaste en lista de espera. Te avisaremos si se libera un cupo.")

    @app.get("/api/mi/empleos", response_model=list[schemas.EmpleoOut], tags=["E3 Protección social"])
    def mis_empleos(trabajador: YoValidado, db: Db):
        postulados = set(db.scalars(select(Postulacion.empleo_id).where(Postulacion.trabajador_id == trabajador.id)))
        return [
            schemas.EmpleoOut(id=e.id, puesto=e.puesto, empresa=e.empresa, distrito=e.distrito, sueldo=e.sueldo,
                              postulado=e.id in postulados)
            for e in db.scalars(select(Empleo).order_by(Empleo.id))
        ]

    @app.post("/api/mi/empleos/{empleo_id}/postulacion", status_code=201, response_model=schemas.Mensaje,
              tags=["E3 Protección social"])
    def postular(empleo_id: int, trabajador: YoValidado, db: Db):
        """HU10 – Postular a una oferta: el perfil se envía a la empresa."""
        empleo = db.get(Empleo, empleo_id)
        if empleo is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Oferta no encontrada")
        if db.scalar(select(Postulacion).where(Postulacion.trabajador_id == trabajador.id,
                                               Postulacion.empleo_id == empleo_id)):
            raise HTTPException(status.HTTP_409_CONFLICT, "Ya postulaste a esta oferta")
        db.add(Postulacion(trabajador_id=trabajador.id, empleo_id=empleo_id))
        db.commit()
        return schemas.Mensaje(mensaje=f"Postulación enviada a {empleo.empresa}. ¡Mucha suerte!")

    @app.post("/api/trabajadores/{trabajador_id}/kits", status_code=201, response_model=schemas.KitOut,
              tags=["E3 Protección social"])
    def registrar_kit(trabajador_id: int, datos: schemas.KitIn, db: Db, usuario: Staff):
        """HU11 – Registrar la entrega del kit; advierte si recibió uno hace menos de 3 meses."""
        trabajador = db.get(Trabajador, trabajador_id)
        if trabajador is None or trabajador.estado != "validado":
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Trabajador validado no encontrado")
        ultimo = db.scalar(select(func.max(EntregaKit.entregado_en)).where(EntregaKit.trabajador_id == trabajador_id))
        reciente = ultimo is not None and utc(ultimo) > datetime.now(timezone.utc) - timedelta(days=DIAS_ENTRE_KITS)
        if reciente and not datos.motivo:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                f"Recibió un kit el {utc(ultimo):%d/%m/%Y}. Indique el motivo para registrar otro.")
        entrega = EntregaKit(trabajador_id=trabajador_id, elementos=",".join(sorted(set(datos.elementos))),
                             motivo=datos.motivo, registrado_por=usuario.usuario)
        db.add(entrega)
        db.commit()
        return schemas.KitOut(id=entrega.id, elementos=entrega.elementos.split(","), motivo=entrega.motivo,
                              registrado_por=entrega.registrado_por, entregado_en=entrega.entregado_en)

    @app.get("/api/trabajadores/{trabajador_id}/kits", response_model=list[schemas.KitOut],
             tags=["E3 Protección social"])
    def kits_de(trabajador_id: int, db: Db, _: Staff):
        return [
            schemas.KitOut(id=k.id, elementos=k.elementos.split(","), motivo=k.motivo,
                           registrado_por=k.registrado_por, entregado_en=k.entregado_en)
            for k in db.scalars(select(EntregaKit).where(EntregaKit.trabajador_id == trabajador_id)
                                .order_by(EntregaKit.entregado_en.desc()))
        ]

    # ---------------- E4: botón de emergencia (HU14) ----------------
    @app.post("/api/mi/emergencia", status_code=201, response_model=schemas.EmergenciaOut, tags=["E4 Alertas"])
    def emergencia(datos: schemas.EmergenciaIn, trabajador: Yo, db: Db):
        """HU14 – Alerta con la ubicación (cruce) al promotor social y al contacto de emergencia.

        La cancelación dentro de los 10 segundos ocurre en el cliente, antes de llamar a este endpoint.
        """
        contacto = db.scalar(select(ContactoEmergencia).where(ContactoEmergencia.trabajador_id == trabajador.id))
        alerta = Alerta(tipo="emergencia", cruce=trabajador.cruce, codigo_seguimiento=nuevo_codigo(),
                        descripcion=f"{trabajador.nombres} (cel. {trabajador.celular}) pidió ayuda. {datos.descripcion}"
                        .strip())
        db.add(alerta)
        db.commit()
        avisados = ["Promotor social de turno"] + ([f"{contacto.nombre} (SMS)"] if contacto else [])
        return schemas.EmergenciaOut(codigo_seguimiento=alerta.codigo_seguimiento, avisados=avisados,
                                     mensaje="Alerta enviada. La ayuda está en camino.")

    # ---------------- E5: usuarios, roles y auditoría (HU16) ----------------
    @app.get("/api/usuarios", response_model=list[schemas.UsuarioOut], tags=["E5 Panel y seguridad"])
    def listar_usuarios(db: Db, _: Admin):
        return list(db.scalars(select(Usuario).order_by(Usuario.id)))

    @app.patch("/api/usuarios/{usuario_id}", response_model=schemas.UsuarioOut, tags=["E5 Panel y seguridad"])
    def cambiar_usuario(usuario_id: int, datos: schemas.UsuarioCambio, db: Db, admin: Admin):
        """HU16 – Cambiar rol o desactivar; cada cambio queda auditado."""
        usuario = db.get(Usuario, usuario_id)
        if usuario is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuario no encontrado")
        if usuario.id == admin.id:
            raise HTTPException(status.HTTP_409_CONFLICT, "No puede modificar su propia cuenta")
        if datos.rol is not None and datos.rol != usuario.rol:
            auditar(db, admin.usuario, "cambiar_rol", f"{usuario.usuario}: {usuario.rol} -> {datos.rol}")
            usuario.rol = datos.rol
        if datos.activo is not None and datos.activo != usuario.activo:
            auditar(db, admin.usuario, "activar" if datos.activo else "desactivar", usuario.usuario)
            usuario.activo = datos.activo
        db.commit()
        return usuario

    @app.get("/api/auditoria", response_model=list[schemas.AuditoriaOut], tags=["E5 Panel y seguridad"])
    def auditoria(db: Db, _: Admin):
        return list(db.scalars(select(Auditoria).order_by(Auditoria.creado_en.desc()).limit(100)))

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


app = create_app()
