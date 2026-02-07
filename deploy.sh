#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if command -v sudo >/dev/null 2>&1; then
  SUDO="sudo"
else
  SUDO=""
fi

echo "[1/4] تثبيت المتطلبات على Ubuntu..."
$SUDO apt-get update -y
$SUDO apt-get install -y python3 python3-venv python3-pip tesseract-ocr tesseract-ocr-ara

if [ ! -d "$ROOT/.venv" ]; then
  echo "[2/4] إنشاء بيئة افتراضية..."
  python3 -m venv "$ROOT/.venv"
fi

# shellcheck disable=SC1091
source "$ROOT/.venv/bin/activate"

echo "[3/4] تثبيت الحزم..."
python -m pip install --upgrade pip
python -m pip install -r "$ROOT/requirements.txt"

mkdir -p "$ROOT/data" "$ROOT/data/debug" "$ROOT/data/photos" "$ROOT/data/cards" "$ROOT/data/logs"

if [ ! -f "$ROOT/.env" ] && [ -f "$ROOT/.env.example" ]; then
  echo "[ENV] إنشاء .env من .env.example"
  cp "$ROOT/.env.example" "$ROOT/.env"
fi

if [ -f "$ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

MODE_ARG="${1:-}"
MODE="${MODE_ARG:-${APP_ENV:-development}}"
START_POSTGRES="${START_POSTGRES:-0}"
START_REDIS="${START_REDIS:-}"

if [[ "$MODE" == "prod" || "$MODE" == "production" ]]; then
  export APP_ENV="production"
  export PRODUCTION=1
else
  export APP_ENV="development"
  export PRODUCTION=0
fi

if [ "$PRODUCTION" = "1" ] && [ -z "${START_REDIS}" ]; then
  START_REDIS=1
fi
START_REDIS="${START_REDIS:-0}"

if [ "$PRODUCTION" = "1" ]; then
  if [ -z "${DATABASE_URL:-}" ] && [ -z "${POSTGRES_URL:-}" ]; then
    if [ "$START_POSTGRES" = "1" ] && command -v docker >/dev/null 2>&1; then
      echo "[DB] تشغيل PostgreSQL عبر Docker..."
      docker compose -f "$ROOT/docker-compose.yml" up -d
      export DATABASE_URL="postgresql://gates:gatespass@localhost:5432/gates_db"
    else
      echo "[DB] DATABASE_URL غير مضبوط. اضبطه أو فعّل START_POSTGRES=1."
      exit 1
    fi
  fi
fi

if [ "$START_REDIS" = "1" ]; then
  echo "[CACHE] تثبيت وتشغيل Redis..."
  $SUDO apt-get install -y redis-server
  if command -v systemctl >/dev/null 2>&1; then
    $SUDO systemctl enable --now redis-server || true
  else
    $SUDO service redis-server start || true
  fi
  if [ -z "${REDIS_URL:-}" ]; then
    export REDIS_URL="redis://localhost:6379/0"
  fi
fi

if [ "$PRODUCTION" = "1" ]; then
  if [ -n "${REDIS_URL:-}" ]; then
    RQ_QUEUE="${RQ_QUEUE:-gates}"
    RQ_LOG="$ROOT/data/logs/rq.log"
    if command -v pgrep >/dev/null 2>&1; then
      if pgrep -f "rq worker ${RQ_QUEUE}" >/dev/null 2>&1; then
        echo "[RQ] Worker already running for queue ${RQ_QUEUE}."
      else
        echo "[RQ] تشغيل عامل RQ في الخلفية..."
        nohup rq worker "$RQ_QUEUE" >>"$RQ_LOG" 2>&1 &
      fi
    else
      echo "[RQ] تشغيل عامل RQ في الخلفية..."
      nohup rq worker "$RQ_QUEUE" >>"$RQ_LOG" 2>&1 &
    fi
  else
    echo "[RQ] REDIS_URL غير مضبوط. لن يتم تشغيل عامل الخلفية."
  fi
fi

echo "[4/4] تشغيل السيرفر على بورت 5000..."
export TESSDATA_PREFIX="$ROOT/tessdata"

if [ "${PRODUCTION:-0}" = "1" ]; then
  WORKERS="${WEB_CONCURRENCY:-2}"
  LOG_LEVEL="${LOG_LEVEL:-info}"
  exec gunicorn app:app \
    -k uvicorn.workers.UvicornWorker \
    --bind 0.0.0.0:5000 \
    --workers "$WORKERS" \
    --timeout 120 \
    --keep-alive 5 \
    --access-logfile "$ROOT/data/logs/access.log" \
    --error-logfile "$ROOT/data/logs/error.log" \
    --log-level "$LOG_LEVEL"
else
  exec uvicorn app:app --host 0.0.0.0 --port 5000
fi
