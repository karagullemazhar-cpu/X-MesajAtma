#!/usr/bin/env bash
# X-MesajAtma - macOS / Linux kurulum
# Kullanim:  bash kur.sh
set -e

cd "$(dirname "$0")"

echo ""
echo "  =================================================="
echo "    X-MesajAtma - Otomatik Kurulum"
echo "  =================================================="
echo ""

if ! command -v python3 >/dev/null 2>&1; then
  echo "  Python 3 bulunamadi."
  echo ""
  echo "  macOS : https://www.python.org/downloads/ adresinden kurun"
  echo "  Ubuntu: sudo apt install -y python3 python3-venv python3-pip"
  echo ""
  exit 1
fi

echo "  [1/3] Python bulundu: $(python3 -V 2>&1)"

if [ ! -x ".venv/bin/python" ]; then
  echo "  [2/3] Calisma ortami hazirlaniyor..."
  python3 -m venv .venv
fi

echo "  [3/3] Gerekli paketler yukleniyor (internet gerekir)..."
.venv/bin/python -m pip install --upgrade pip --quiet --disable-pip-version-check
.venv/bin/python -m pip install -r requirements.txt --quiet --disable-pip-version-check

chmod +x baslat.sh 2>/dev/null || true

echo ""
echo "  =================================================="
echo "    KURULUM TAMAM"
echo "  =================================================="
echo ""
echo "    Calistirmak icin:   ./baslat.sh"
echo "    Panel adresi:       http://127.0.0.1:5077"
echo ""
echo "  =================================================="
echo ""
