FROM python:3.11-slim

# Dependencias del sistema para cfgrib (libeccodes) y netCDF4
RUN apt-get update && apt-get install -y --no-install-recommends \
        libeccodes0 \
        libeccodes-tools \
        libnetcdf22 \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY download_gfs.py scheduler.py ./

# Volumen donde se persisten los NetCDF (compartido con THREDDS)
VOLUME ["/data/actual"]

# El scheduler se autodescribe en logs y reintenta solo
CMD ["python", "-u", "scheduler.py"]
