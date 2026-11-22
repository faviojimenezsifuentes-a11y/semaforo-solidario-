"""Catálogo inicial de programas sociales, capacitaciones y empleos (HU09, HU10).

En el piloto lo administra la municipalidad u ONG aliada; aquí se cargan datos de
ejemplo la primera vez que arranca la aplicación (solo si las tablas están vacías).
"""

from datetime import datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Capacitacion, Empleo, Programa

PROGRAMAS = [
    {
        "nombre": "SIS – Seguro Integral de Salud",
        "descripcion": "Cobertura de salud gratuita para personas sin otro seguro.",
        "requisitos": "Documento de identidad vigente y no contar con otro seguro de salud.",
        "lugar": "Establecimiento de salud más cercano o módulo SIS de la municipalidad",
        "documentos": "DNI,CE",
    },
    {
        "nombre": "Orientación legal y regularización migratoria",
        "descripcion": "Asesoría gratuita para regularizar tu situación migratoria y acceder a servicios.",
        "requisitos": "Carné de extranjería o PTP.",
        "lugar": "Oficina de atención al migrante de la ONG aliada",
        "documentos": "CE,PTP",
    },
    {
        "nombre": "Capacitación laboral juvenil",
        "descripcion": "Cursos técnicos gratuitos con certificación para jóvenes de 18 a 29 años.",
        "requisitos": "Tener entre 18 y 29 años y documento de identidad.",
        "lugar": "Centro de empleo de la municipalidad",
        "documentos": "DNI,CE,PTP",
        "edad_max": 29,
    },
    {
        "nombre": "Bolsa de trabajo municipal",
        "descripcion": "Registro en la bolsa de trabajo y acompañamiento para conseguir empleo formal.",
        "requisitos": "Documento de identidad y número de celular.",
        "lugar": "Centro de empleo de la municipalidad",
        "documentos": "DNI,CE,PTP",
    },
    {
        "nombre": "Programa de apoyo alimentario",
        "descripcion": "Acceso a comedores populares y canasta básica para familias vulnerables.",
        "requisitos": "Documento de identidad y evaluación socioeconómica del promotor.",
        "lugar": "Gerencia de Desarrollo Social de la municipalidad",
        "documentos": "DNI,CE,PTP",
    },
]

CAPACITACIONES = [
    ("Atención al cliente y ventas", 7, "Centro de empleo municipal – Aula 2", 20),
    ("Seguridad vial y primeros auxilios", 10, "Compañía de bomberos del distrito", 15),
    ("Emprendimiento y finanzas personales", 14, "ONG aliada – Sala de capacitación", 25),
]

EMPLEOS = [
    ("Operario de limpieza", "Servicios Generales Lima S.A.C.", "San Isidro", 1130),
    ("Ayudante de almacén", "Distribuidora Andina S.A.", "Ate", 1200),
    ("Lavador de autos", "Car Wash Express", "Surquillo", 1130),
    ("Repartidor en moto (con licencia)", "Rápido Delivery Perú", "Miraflores", 1500),
]


# Cruces del piloto con su distrito y coordenadas aproximadas (HU15: filtro por distrito y mapa).
CRUCES = {
    "av. javier prado / av. arequipa": ("San Isidro", -12.0907, -77.0347),
    "av. brasil / av. javier prado": ("Magdalena del Mar", -12.0918, -77.0640),
    "av. benavides / av. república de panamá": ("Miraflores", -12.1268, -77.0208),
    "av. angamos / av. paseo de la república": ("Surquillo", -12.1131, -77.0272),
    "av. la marina / av. universitaria": ("San Miguel", -12.0789, -77.0857),
}
NOMBRES_CRUCES = [
    "Av. Javier Prado / Av. Arequipa",
    "Av. Brasil / Av. Javier Prado",
    "Av. Benavides / Av. República de Panamá",
    "Av. Angamos / Av. Paseo de la República",
    "Av. La Marina / Av. Universitaria",
]
SIN_DISTRITO = "Sin distrito asignado"


def ubicar_cruce(cruce: str) -> tuple[str, float | None, float | None]:
    """Distrito y coordenadas de un cruce conocido; los demás quedan sin ubicar en el mapa."""
    distrito, lat, lng = CRUCES.get(" ".join(cruce.lower().split()), (SIN_DISTRITO, None, None))
    return distrito, lat, lng


def cargar_catalogo(db: Session) -> None:
    if db.scalar(select(Programa).limit(1)) is None:
        db.add_all(Programa(**p) for p in PROGRAMAS)
    if db.scalar(select(Capacitacion).limit(1)) is None:
        hoy = datetime.now(timezone.utc).date()
        for nombre, dias, lugar, cupos in CAPACITACIONES:
            fecha = datetime.combine(hoy + timedelta(days=dias), time(15, 0), tzinfo=timezone.utc)
            db.add(Capacitacion(nombre=nombre, fecha=fecha, lugar=lugar, cupos=cupos))
    if db.scalar(select(Empleo).limit(1)) is None:
        db.add_all(Empleo(puesto=p, empresa=e, distrito=d, sueldo=s) for p, e, d, s in EMPLEOS)
    db.commit()
