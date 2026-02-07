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
USE_SYSTEMD="${USE_SYSTEMD:-}"
HARDENING_ENABLE="${HARDENING_ENABLE:-}"
FIREWALL_ENABLE="${FIREWALL_ENABLE:-}"
FIREWALL_ALLOW_PORTS="${FIREWALL_ALLOW_PORTS:-22,80,443,5000}"
LOGROTATE_ENABLE="${LOGROTATE_ENABLE:-}"
RAW_RETENTION_DAYS="${RAW_RETENTION_DAYS:-2}"
DEBUG_RETENTION_DAYS="${DEBUG_RETENTION_DAYS:-30}"
AUTO_INSTALL_DOCKER="${AUTO_INSTALL_DOCKER:-}"

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

if [ "$PRODUCTION" = "1" ] && [ -z "${USE_SYSTEMD}" ] && command -v systemctl >/dev/null 2>&1; then
  USE_SYSTEMD=1
fi
USE_SYSTEMD="${USE_SYSTEMD:-0}"

if [ "$PRODUCTION" = "1" ] && [ -z "${HARDENING_ENABLE}" ]; then
  HARDENING_ENABLE=1
fi
HARDENING_ENABLE="${HARDENING_ENABLE:-0}"
if [ "$HARDENING_ENABLE" = "1" ] && [ -z "${FIREWALL_ENABLE}" ]; then
  FIREWALL_ENABLE=1
fi
FIREWALL_ENABLE="${FIREWALL_ENABLE:-0}"
if [ "$HARDENING_ENABLE" = "1" ] && [ -z "${LOGROTATE_ENABLE}" ]; then
  LOGROTATE_ENABLE=1
fi
LOGROTATE_ENABLE="${LOGROTATE_ENABLE:-0}"

if [ "$HARDENING_ENABLE" = "1" ] && [ "$FIREWALL_ENABLE" = "1" ]; then
  echo "[SECURITY] إعداد جدار الحماية..."
  $SUDO apt-get install -y ufw
  $SUDO ufw default deny incoming || true
  $SUDO ufw default allow outgoing || true
  IFS=',' read -ra PORT_LIST <<< "$FIREWALL_ALLOW_PORTS"
  for port in "${PORT_LIST[@]}"; do
    port="$(echo "$port" | xargs)"
    if [ -n "$port" ]; then
      $SUDO ufw allow "${port}/tcp" || true
    fi
  done
  $SUDO ufw --force enable || true
fi

if [ "$HARDENING_ENABLE" = "1" ] && [ "$LOGROTATE_ENABLE" = "1" ]; then
  echo "[SECURITY] إعداد logrotate..."
  $SUDO apt-get install -y logrotate
  if command -v logrotate >/dev/null 2>&1; then
    $SUDO tee /etc/logrotate.d/gates-app >/dev/null <<EOF
$ROOT/data/logs/*.log {
  size 50M
  rotate 5
  compress
  missingok
  notifempty
  copytruncate
}
EOF
  fi
fi

if [ -n "${RAW_RETENTION_DAYS}" ]; then
  if [ -d "$ROOT/data/raw" ]; then
    find "$ROOT/data/raw" -type f -mtime +"$RAW_RETENTION_DAYS" -delete || true
  fi
fi
if [ -n "${DEBUG_RETENTION_DAYS}" ]; then
  if [ -d "$ROOT/data/debug" ]; then
    find "$ROOT/data/debug" -type f -mtime +"$DEBUG_RETENTION_DAYS" -delete || true
  fi
fi

if [ "$PRODUCTION" = "1" ] && [ -z "${AUTO_INSTALL_DOCKER}" ]; then
  AUTO_INSTALL_DOCKER=1
fi
AUTO_INSTALL_DOCKER="${AUTO_INSTALL_DOCKER:-0}"

ensure_docker() {
  if command -v docker >/dev/null 2>&1; then
    return 0
  fi
  if [ "$AUTO_INSTALL_DOCKER" != "1" ]; then
    return 1
  fi
  echo "[DB] تثبيت Docker..."
  $SUDO apt-get install -y docker.io docker-compose-plugin
  if command -v systemctl >/dev/null 2>&1; then
    $SUDO systemctl enable --now docker || true
  else
    $SUDO service docker start || true
  fi
  return 0
}

if [ "$PRODUCTION" = "1" ]; then
  if [ -z "${DATABASE_URL:-}" ] && [ -z "${POSTGRES_URL:-}" ]; then
    if [ "$START_POSTGRES" = "1" ]; then
      if ! command -v docker >/dev/null 2>&1; then
        if ! ensure_docker; then
          echo "[DB] Docker غير مثبت. فعّل AUTO_INSTALL_DOCKER=1 أو ثبّته يدوياً."
          exit 1
        fi
      fi
      POSTGRES_PORT="${POSTGRES_PORT:-5432}"
      if command -v ss >/dev/null 2>&1; then
        if ss -lnt | awk '{print $4}' | grep -q ":${POSTGRES_PORT}$"; then
          if [ "${POSTGRES_PORT}" = "5432" ]; then
            POSTGRES_PORT="5433"
            export POSTGRES_PORT
            echo "[DB] المنفذ 5432 مستخدم، التحويل إلى 5433..."
          else
            echo "[DB] المنفذ ${POSTGRES_PORT} مستخدم. غيّر POSTGRES_PORT أو عطّل START_POSTGRES."
            exit 1
          fi
        fi
      fi
      echo "[DB] تشغيل PostgreSQL عبر Docker..."
      DOCKER_COMPOSE="docker compose"
      if ! docker compose version >/dev/null 2>&1; then
        if command -v docker-compose >/dev/null 2>&1; then
          DOCKER_COMPOSE="docker-compose"
        else
          if [ "$AUTO_INSTALL_DOCKER" = "1" ]; then
            $SUDO apt-get install -y docker-compose-plugin
          fi
        fi
      fi
      $DOCKER_COMPOSE -f "$ROOT/docker-compose.yml" up -d
      POSTGRES_DB="${POSTGRES_DB:-gates_db}"
      POSTGRES_USER="${POSTGRES_USER:-gates}"
      POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-gatespass}"
      export DATABASE_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@localhost:${POSTGRES_PORT}/${POSTGRES_DB}"
    else
      echo "[DB] DATABASE_URL غير مضبوط. اضبطه أو فعّل START_POSTGRES=1."
      exit 1
    fi
  fi
fi

if [ "$START_REDIS" = "1" ]; then
  echo "[CACHE] تثبيت وتشغيل Redis..."
  $SUDO apt-get install -y redis-server
  if [ -f /etc/redis/redis.conf ]; then
    $SUDO sed -i "s/^#*bind .*/bind 127.0.0.1 ::1/" /etc/redis/redis.conf || true
    $SUDO sed -i "s/^#*protected-mode .*/protected-mode yes/" /etc/redis/redis.conf || true
  fi
  if command -v systemctl >/dev/null 2>&1; then
    $SUDO systemctl enable --now redis-server || true
    $SUDO systemctl restart redis-server || true
  else
    $SUDO service redis-server restart || true
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
  if [ "$USE_SYSTEMD" = "1" ] && command -v systemctl >/dev/null 2>&1; then
    SERVICE_USER="$(id -un)"
    APP_SERVICE="/etc/systemd/system/gates-app.service"
    RQ_SERVICE="/etc/systemd/system/gates-rq.service"

    echo "[SYSTEMD] إعداد خدمة Gates API..."
    $SUDO tee "$APP_SERVICE" >/dev/null <<EOF
[Unit]
Description=Gates Hyde Park API
After=network.target redis-server.service docker.service
Wants=network.target

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$ROOT
EnvironmentFile=$ROOT/.env
Environment=PYTHONUNBUFFERED=1
ExecStart=$ROOT/.venv/bin/gunicorn app:app -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:5000 --workers \$WEB_CONCURRENCY --timeout 120 --keep-alive 5 --access-logfile $ROOT/data/logs/access.log --error-logfile $ROOT/data/logs/error.log --log-level \$LOG_LEVEL
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

    echo "[SYSTEMD] إعداد خدمة RQ Worker..."
    $SUDO tee "$RQ_SERVICE" >/dev/null <<EOF
[Unit]
Description=Gates Hyde Park RQ Worker
After=network.target redis-server.service
Wants=network.target

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$ROOT
EnvironmentFile=$ROOT/.env
Environment=PYTHONUNBUFFERED=1
ExecStart=$ROOT/.venv/bin/rq worker \$RQ_QUEUE
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

    $SUDO systemctl daemon-reload
    $SUDO systemctl enable --now gates-app.service
    if [ -n "${REDIS_URL:-}" ]; then
      $SUDO systemctl enable --now gates-rq.service
    fi
    echo "[SYSTEMD] الخدمات شغالة: gates-app و gates-rq"
    exit 0
  fi

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
