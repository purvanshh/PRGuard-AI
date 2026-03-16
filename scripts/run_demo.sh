#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "[demo] Starting production docker-compose stack..."
docker compose -f deploy/docker-compose.prod.yml up -d --build

echo "[demo] Waiting for API to become healthy..."
sleep 10

echo "[demo] Simulating a PR webhook using scripts/test_webhook.py..."
python scripts/test_webhook.py || echo "[demo] Warning: webhook simulation failed (check logs)."

echo "[demo] Run benchmark evaluation..."
python scripts/run_benchmark.py || echo "[demo] Warning: benchmark run failed (check logs)."

echo "[demo] Open the following URLs in your browser:"
echo "  - API health:       http://localhost:8000/health"
echo "  - Dashboard:        http://localhost:8000/dashboard"
echo "  - Prometheus:       http://localhost:9090"
echo "  - Grafana:          http://localhost:3000 (admin/admin by default)"

