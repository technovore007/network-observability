#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/home/admin0/network-observability"

cd "$PROJECT_DIR"

set -a
source "$PROJECT_DIR/config/routers.env"
set +a

exec "$PROJECT_DIR/.venv/bin/python" -u -m collector.service
