#!/usr/bin/env bash
# Levanta OpenCaption Live con Docker Compose.
# Uso: bash iniciar.sh [--motor local|gemini|mock] [--con-ollama]
set -euo pipefail
cd "$(dirname "$0")"

MOTOR=""
CON_OLLAMA=0
while [ $# -gt 0 ]; do
  case "$1" in
    --motor) MOTOR="${2:-}"; shift 2 ;;
    --con-ollama) CON_OLLAMA=1; shift ;;
    -h|--help) sed -n '2,3p' "$0"; exit 0 ;;
    *) echo "Opción desconocida: $1 (ver --help)" >&2; exit 1 ;;
  esac
done

command -v docker >/dev/null 2>&1 || { echo "No encontré Docker. Instalá Docker Desktop o Docker Engine + Compose." >&2; exit 1; }
docker info >/dev/null 2>&1 || { echo "Docker no está corriendo: abrilo y esperá a que el motor arranque." >&2; exit 1; }

get_env() { grep "^$1=" .env | tail -n 1 | cut -d= -f2- || true; }
set_env() {
  if grep -q "^$1=" .env; then
    sed -i.bak "s|^$1=.*|$1=$2|" .env && rm -f .env.bak
  else
    printf '%s=%s\n' "$1" "$2" >> .env
  fi
}

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Creé .env a partir de .env.example."
fi
if [ -z "$(get_env INGEST_TOKEN)" ]; then
  set_env INGEST_TOKEN "$(head -c 24 /dev/urandom | base64 | tr '+/' '-_' | tr -d '=\n')"
  echo "Generé un INGEST_TOKEN aleatorio en .env."
fi

MOTOR_ELEGIDO="$MOTOR"
MOTOR="${MOTOR:-$(get_env CAPTION_ENGINE)}"
MOTOR="${MOTOR:-local}"
case "$MOTOR" in
  local|gemini|mock) ;;
  *) echo "Motor inválido: $MOTOR (usar local, gemini o mock)" >&2; exit 1 ;;
esac
if [ "$MOTOR" = "gemini" ] && [ -z "$(get_env GEMINI_API_KEY)" ]; then
  echo "El motor gemini necesita GEMINI_API_KEY en .env." >&2
  exit 1
fi
[ -n "$MOTOR_ELEGIDO" ] && set_env CAPTION_ENGINE "$MOTOR"

COMPOSE=(docker compose -f docker-compose.yml)
if [ "$CON_OLLAMA" = 1 ]; then
  [ "$MOTOR" = "local" ] || echo "Aviso: Ollama solo se usa con el motor local (el actual es $MOTOR)."
  COMPOSE+=(-f docker-compose.ollama.yml)
fi

echo "Levantando OpenCaption Live (motor: $MOTOR)..."
"${COMPOSE[@]}" up -d --build

PORT="$(get_env PORT)"
PORT="${PORT:-8000}"
URL="http://localhost:$PORT"
printf 'Esperando a que responda %s ' "$URL"
for _ in $(seq 1 90); do
  # 127.0.0.1: Docker publica el puerto solo en IPv4 (localhost puede ir a ::1).
  if curl -fs "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
    echo " listo."
    break
  fi
  printf '.'
  sleep 2
done

cat <<EOF

  Vista de audiencia:  $URL
  Emitir audio:        $URL/admin.html
  Overlay para OBS:    $URL/overlay.html?session=<sesión>&lang=es
  Token de emisión:    $(get_env INGEST_TOKEN)

  Logs:     ${COMPOSE[*]} logs -f
  Detener:  ${COMPOSE[*]} down
EOF
if [ "$MOTOR" = "local" ]; then
  echo "  La primera vez el motor local descarga sus modelos (~550 MB): mirá los logs."
fi
