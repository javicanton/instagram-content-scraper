#!/usr/bin/env bash
# Crea el entorno Python del proyecto evitando conflictos conda / arquitectura.
set -euo pipefail

cd "$(dirname "$0")"

pick_python() {
  if [ -n "${PYTHON:-}" ] && "$PYTHON" -c "import platform; exit(0 if platform.machine() == 'arm64' else 1)" 2>/dev/null; then
    echo "$PYTHON"
    return
  fi
  for candidate in \
    /opt/miniconda3/bin/python3.13 \
    /opt/miniconda3/bin/python3 \
    /opt/homebrew/bin/python3.13 \
    /opt/homebrew/bin/python3; do
    if [ -x "$candidate" ] && "$candidate" -c "import platform; exit(0 if platform.machine() == 'arm64' else 1)" 2>/dev/null; then
      echo "$candidate"
      return
    fi
  done
  echo ""
}

if [ -n "${CONDA_PREFIX:-}" ]; then
  echo "AVISO: conda activo ($CONDA_PREFIX). Desactivando para evitar mezcla arm64/x86_64..."
  # shellcheck disable=SC1091
  conda deactivate 2>/dev/null || true
fi

PY=$(pick_python)
if [ -z "$PY" ]; then
  echo "ERROR: no se encontró Python 3 arm64."
  echo "Instala Miniconda (Apple Silicon) o: brew install python@3.13"
  exit 1
fi

echo "Usando: $PY ($("$PY" -c "import platform; print(platform.machine())"))"

if [ -d .venv ]; then
  ARCH=$(file .venv/bin/python3 2>/dev/null | grep -o 'arm64\|x86_64' || echo "unknown")
  if [ "$ARCH" != "arm64" ]; then
    echo "Eliminando .venv incompatible ($ARCH)..."
    rm -rf .venv
  fi
fi

if [ ! -d .venv ]; then
  "$PY" -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt

echo ""
echo "Entorno listo. Actívalo con:"
echo "  source .venv/bin/activate"
