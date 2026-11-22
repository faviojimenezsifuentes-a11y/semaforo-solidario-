# 🚦 Semáforo Solidario

Plataforma web para **formalizar, proteger y apoyar a las personas que limpian parabrisas en los semáforos**
(jóvenes, migrantes venezolanos y otros), y para **detectar a menores de edad trabajando** en los cruces.

Proyecto académico — Proyecto Final de Carrera III, Práctica Calificada 2.

- **Backlog (Jira):** proyecto `LIMP` — https://faviojimenezsifuentes.atlassian.net/browse/LIMP
- **Solución desplegada:** ver la sección *Despliegue*.

## Funcionalidades y trazabilidad con Jira

La aplicación cubre las 16 historias priorizadas del backlog (HU17 quedó como *Won't* en esta versión).

| Historia | Jira | Endpoint |
|---|---|---|
| HU01 Registro con documento (DNI/CE/PTP); menores → alerta | LIMP-6 | `POST /api/trabajadores` |
| HU02 Ingreso con celular y código OTP (5 min, bloqueo tras 5 fallos) | LIMP-7 | `POST /api/auth/otp/solicitar`, `POST /api/auth/otp/verificar` |
| HU03 Validación por el promotor social | LIMP-8 | `POST /api/trabajadores/{id}/validacion` |
| HU04 Registrar o cambiar cruce y horario (con historial) | LIMP-9 | `PUT /api/mi/cruce` |
| HU05 QR personal (solo validados) | LIMP-10 | `GET /api/qr/{token}.svg` |
| HU06 Propina con Yape/Plin (pago simulado) | LIMP-11 | `POST /api/propinas` |
| HU07 Historial de propinas (hoy/semana), solo el propio trabajador | LIMP-12 | `GET /api/mi/propinas` |
| HU08 Calificar el servicio | LIMP-13 | `POST /api/propinas/{id}/calificacion` |
| HU09 Programas sociales según documento y edad; solicitud de orientación | LIMP-14 | `GET /api/mi/programas`, `POST /api/mi/programas/{id}/solicitud` |
| HU10 Capacitaciones con cupos / lista de espera y postulación a empleos | LIMP-15 | `POST /api/mi/capacitaciones/{id}/inscripcion`, `POST /api/mi/empleos/{id}/postulacion` |
| HU11 Entrega de kits de seguridad (advierte si hubo una en < 3 meses) | LIMP-16 | `POST /api/trabajadores/{id}/kits` |
| HU12 Reporte anónimo de menor | LIMP-17 | `POST /api/alertas` |
| HU13 Derivación a DEMUNA; alertas sin atender 48 h → vencidas | LIMP-18 | `POST /api/alertas/{id}/derivar` |
| HU14 Botón de emergencia (mantener 3 s, cancelar en 10 s) | LIMP-19 | `POST /api/mi/emergencia` |
| HU15 Panel por cruce (trabajadores, alertas, kits, propinas) | LIMP-20 | `GET /api/panel` |
| HU16 Usuarios, roles, desactivación y auditoría | LIMP-21 | `POST/GET /api/usuarios`, `PATCH /api/usuarios/{id}`, `GET /api/auditoria` |

**Sobre el OTP:** el piloto no tiene un proveedor de SMS contratado, así que con `OTP_DEMO=true` (valor por
defecto) el código se muestra en pantalla. Con un proveedor real se define `OTP_DEMO=false` y el código
solo viaja por SMS. El código nunca se guarda en claro (HMAC-SHA256) y es de un solo uso.

Documentación interactiva de la API (OpenAPI): `/docs`.

## Arquitectura

```
Navegador (HTML/CSS/JS)  ──HTTPS──▶  FastAPI (Uvicorn, contenedor Docker en Render)
                                      ├─ Validación (Pydantic)
                                      ├─ Autenticación: OTP + JWT (trabajador), contraseña + JWT (promotor/admin)
                                      ├─ ORM SQLAlchemy ──▶ Base de datos (SQLite / PostgreSQL)
                                      └─ Servicios externos: pasarela Yape/Plin (simulada), QR (segno)
```

## Ejecutar en local

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env       # y define tus valores
export $(cat .env | xargs) # Windows: definir variables manualmente
uvicorn app.main:app --reload
# http://localhost:8000
```

Pruebas: `pytest --cov=app`

## Estrategia de ramas

- `main` → producción. Solo recibe cambios mediante **Pull Request** desde `test`; cada push despliega a Render.
- `test` → integración y pruebas. Cada push ejecuta todo el pipeline excepto el despliegue.

## Pipeline CI/CD (GitHub Actions — `.github/workflows/ci-cd.yml`)

| Etapa | Herramienta | Qué hace |
|---|---|---|
| Build | pip + ruff | Instala dependencias fijadas y valida el código (incluye reglas de seguridad `S`) |
| Test | pytest + pytest-cov | 48 pruebas unitarias y de integración trazadas a las historias; cobertura mínima 80 % |
| SAST | Bandit | Analiza el código Python en busca de fallas de seguridad |
| Dependencias | pip-audit | Busca CVE conocidas en las librerías |
| Secretos | Gitleaks | Detecta claves o tokens filtrados en todo el historial |
| Imagen | Docker + Trivy | Construye la imagen, la escanea (CRITICAL/HIGH) y hace smoke test |
| Deploy | Render deploy hook | Solo en `main` y solo si todo lo anterior pasó; verifica `/health` |

Además, **Dependabot** propone actualizaciones semanales de dependencias, actions e imagen base.

## Seguridad implementada en la aplicación

- Contraseñas con PBKDF2-SHA256 (240 000 iteraciones, sal aleatoria); tokens JWT con expiración.
- OTP de un solo uso guardado como HMAC, con vencimiento de 5 minutos y bloqueo de 15 minutos tras 5 intentos fallidos;
  la respuesta no revela si un celular está registrado.
- El historial de ingresos solo lo ve el propio trabajador con su sesión (no basta con conocer su QR, que es público).
- Control de acceso por rol en los endpoints internos.
- Validación estricta de entradas (Pydantic) y ORM parametrizado (sin SQL inyectable).
- Datos personales protegidos: documento enmascarado, reportes de conductores anónimos (Ley N.° 29733).
- Cabeceras de seguridad: CSP, `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy`. La interfaz no carga nada de
  terceros (tipografía Barlow servida desde el propio dominio, licencia SIL OFL).
- Secretos solo en variables de entorno; contenedor ejecutado con usuario sin privilegios.

## Despliegue (Render)

1. En Render: **New → Blueprint** y seleccionar este repositorio (usa `render.yaml`), o **New → Web Service → Docker**.
2. Definir las variables `ADMIN_USER`, `ADMIN_PASSWORD`, `PROMOTOR_USER` y `PROMOTOR_PASSWORD`.
3. Copiar el **Deploy Hook** del servicio y guardarlo en GitHub como secreto `RENDER_DEPLOY_HOOK`;
   guardar la URL pública como variable `RENDER_URL`.
