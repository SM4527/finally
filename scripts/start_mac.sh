#!/usr/bin/env bash
# Start the FinAlly container. Pass --build to force an image rebuild.
set -euo pipefail
cd "$(dirname "$0")/.."

IMAGE=finally
CONTAINER=finally
URL=http://localhost:8000

if [[ "${1:-}" == "--build" ]] || ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  docker build -t "$IMAGE" .
fi

[[ -f .env ]] || { echo "Missing .env; copy .env.example to .env first."; exit 1; }

docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
docker run -d --name "$CONTAINER" \
  -v finally-data:/app/db \
  -p 8000:8000 \
  --env-file .env \
  "$IMAGE" >/dev/null

echo "FinAlly is running at $URL"
if command -v open >/dev/null; then open "$URL"
elif command -v xdg-open >/dev/null; then xdg-open "$URL" >/dev/null 2>&1 || true
fi
