#!/usr/bin/env bash
# © Itzhar Olivera Solutions & Strategy — Tom Yair Tommy Itzhar Olivera
# Quickstart: brings up the full local stack and seeds the workplan

set -euo pipefail

cd "$(dirname "$0")/.."

if [[ ! -f .env ]]; then
  echo "→ Creating .env from .env.example"
  cp .env.example .env
  echo "  ⚠  Edit .env with real credentials before running migrations"
fi

echo "→ Building and starting containers"
docker-compose up -d --build

echo "→ Waiting for backend to be healthy"
for i in {1..30}; do
  if curl -fsS http://localhost:5000/health > /dev/null 2>&1; then
    echo "  ✓ Backend ready"
    break
  fi
  sleep 2
done

echo "→ Running database migrations"
docker-compose exec -T backend flask db upgrade || docker-compose exec -T backend flask db init

echo "→ Seeding migration workplan (54 tasks across 7 phases)"
curl -fsS -X POST http://localhost:5000/api/v1/migration/seed | python3 -m json.tool

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  Migration Platform is ready"
echo "  • UI:        http://localhost:3000"
echo "  • API:       http://localhost:5000"
echo "  • Flower:    http://localhost:5555  (Celery monitoring)"
echo "  • Grafana:   http://localhost:3001  (admin / admin)"
echo "  • MinIO:     http://localhost:9001  (minioadmin / minioadmin)"
echo "  • Prometheus http://localhost:9090"
echo "═══════════════════════════════════════════════════════════════"
