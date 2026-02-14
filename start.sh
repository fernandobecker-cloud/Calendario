#!/usr/bin/env bash
set -euo pipefail

PORT="${PORT:-10000}"

# Safety net: se o build React não existir, tenta gerar antes de subir o backend.
if [ ! -f "frontend/dist/index.html" ]; then
  echo "[start.sh] frontend/dist não encontrado. Gerando build React..."
  if ! command -v npm >/dev/null 2>&1; then
    echo "[start.sh] ERRO: npm não está disponível no ambiente."
    echo "[start.sh] Configure o Build Command na Render para rodar:"
    echo "pip install -r requirements.txt && cd frontend && npm ci && npm run build"
    exit 1
  fi
  cd frontend
  if [ -f "package-lock.json" ]; then
    npm ci
  else
    npm install
  fi
  npm run build
  cd ..
fi

exec python3 -m uvicorn server:app --host 0.0.0.0 --port "$PORT"
