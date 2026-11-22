# Imagen mínima y sin privilegios para producción
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

WORKDIR /app

# Parches de seguridad del sistema operativo (p. ej. zlib) detectados por Trivy
RUN apt-get update && apt-get upgrade -y --no-install-recommends && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# Actualiza pip y setuptools (versión de la imagen base vulnerable a CVE-2025-47273)
RUN pip install --upgrade pip "setuptools>=78.1.1" && pip install -r requirements.txt

COPY app ./app

# Usuario sin privilegios (no root)
RUN useradd --create-home --uid 10001 appuser && chown -R appuser /app
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://localhost:{os.environ.get(\"PORT\",\"8000\")}/health')"

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
