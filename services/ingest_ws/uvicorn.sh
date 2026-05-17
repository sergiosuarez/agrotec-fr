#!/usr/bin/env bash
uvicorn app:app \
  --host ${APP_HOST:-0.0.0.0} \
  --port ${APP_PORT:-8000} \
  --workers ${APP_WORKERS:-4} \
  --ws websockets