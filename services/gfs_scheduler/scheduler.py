"""
scheduler.py — Loop principal del scheduler GFS.

Ejecuta `descargar_gfs()` al arrancar y luego cada GFS_INTERVAL_HOURS (default 6h).
Reintenta tras GFS_RETRY_MINUTES (default 30 min) si falla la descarga del archivo principal.
"""
from __future__ import annotations

import logging
import os
import sys
import time
import traceback

from download_gfs import descargar_gfs

INTERVAL_HOURS  = float(os.getenv("GFS_INTERVAL_HOURS", "6"))
RETRY_MINUTES   = float(os.getenv("GFS_RETRY_MINUTES", "30"))


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )
    log = logging.getLogger("scheduler")
    log.info("Agrotec GFS scheduler iniciado (intervalo=%.1fh, retry=%.1fmin)",
             INTERVAL_HOURS, RETRY_MINUTES)

    while True:
        try:
            result = descargar_gfs()
            log.info("OK — proximo run en %.1fh", INTERVAL_HOURS)
            time.sleep(INTERVAL_HOURS * 3600)
        except KeyboardInterrupt:
            log.info("Interrupcion solicitada, saliendo")
            break
        except Exception as exc:
            log.error("Fallo descarga GFS: %s", exc)
            log.debug("Trace:\n%s", traceback.format_exc())
            log.info("Reintentando en %.1f min", RETRY_MINUTES)
            time.sleep(RETRY_MINUTES * 60)


if __name__ == "__main__":
    main()
