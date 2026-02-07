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

if [ -f "$ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

MODE_ARG="${1:-}"
MODE="${MODE_ARG:-${APP_ENV:-development}}"

if [[ "$MODE" == "prod" || "$MODE" == "production" ]]; then
  export APP_ENV="production"
  export PRODUCTION=1
else
  export APP_ENV="development"
  export PRODUCTION=0
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
