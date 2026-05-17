FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl libpq5 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copia el codigo: app/ (FastAPI), static/ (geovisor), tests/
COPY app ./app
COPY static ./static
COPY tests ./tests
COPY uvicorn.sh .
RUN chmod +x uvicorn.sh

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["bash", "uvicorn.sh"]
