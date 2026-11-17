#!/usr/bin/env bash
# X-MesajAtma - macOS / Linux baslatma
cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
  echo ""
  echo "  Once kurulum yapin:  bash kur.sh"
  echo ""
  exit 1
fi

echo ""
echo "  X-MesajAtma baslatiliyor..."
echo "  Panel: http://127.0.0.1:5077"
echo "  Durdurmak icin Ctrl+C"
echo ""

XMA_AC=1 .venv/bin/python app.py
