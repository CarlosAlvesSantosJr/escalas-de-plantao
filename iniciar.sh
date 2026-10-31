#!/usr/bin/env sh
# Inicia a Escala de Plantão (macOS / Linux). Uso: ./iniciar.sh
set -e
cd "$(dirname "$0")"

if ! docker info >/dev/null 2>&1; then
  echo "Abra o Docker Desktop e rode este script de novo."
  exit 1
fi

mkdir -p dados
docker compose up -d --build

printf "Aguardando a aplicação"
until curl -fs http://localhost:8080/saude >/dev/null; do printf "."; sleep 2; done
echo " pronto!"

URL=http://localhost:8080
(command -v open >/dev/null && open "$URL") || (command -v xdg-open >/dev/null && xdg-open "$URL") || echo "Abra $URL no navegador."
