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

mkdir -p "$ROOT/data" "$ROOT/data/debug"

echo "[4/4] تشغيل السيرفر على بورت 5000..."
export TESSDATA_PREFIX="$ROOT/tessdata"
exec uvicorn app:app --host 0.0.0.0 --port 5000
