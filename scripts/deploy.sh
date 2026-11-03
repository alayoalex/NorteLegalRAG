#!/usr/bin/env bash
# Despliega el checkout actual en el servidor y verifica los dominios públicos.
# Requisitos: .env con POSTGRES_PASSWORD, red externa mizpa-network y los sitios del Caddy compartido.
set -euo pipefail
cd "$(dirname "$0")/.."

docker compose -f docker-compose.yml -f docker-compose.prod.yml up --detach --build --wait --wait-timeout 300

# La app es pública. Trazas y métricas deben exigir credenciales (401): si responden 200, Caddy está mal configurado.
check() {
  local expected=$1 url=$2 code
  code=$(curl --silent --output /dev/null --write-out '%{http_code}' --max-time 10 "$url")
  if [[ $code != "$expected" ]]; then
    echo "FALLO: $url devolvió $code (se esperaba $expected)" >&2
    exit 1
  fi
  echo "ok $code $url"
}
check 200 https://nortelegal.mizpa.io/readyz
check 401 https://nortelegal-traces.mizpa.io/
check 401 https://nortelegal-metrics.mizpa.io/metrics
