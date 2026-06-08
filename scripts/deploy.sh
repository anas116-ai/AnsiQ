#!/usr/bin/env bash
# ────────────────────────────────────────────────────────────────────────────
# AnsiQ Production Deployment Script
# ────────────────────────────────────────────────────────────────────────────
# Usage:
#   ./scripts/deploy.sh                   # Deploy with docker compose
#   ./scripts/deploy.sh --monitoring      # Deploy with monitoring stack
#   ./scripts/deploy.sh --build           # Force rebuild
#   ./scripts/deploy.sh --env production  # Set environment
#
# Prerequisites:
#   - Docker & Docker Compose v2
#   - .env file with production secrets
# ────────────────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

# ── Colors ──
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
log_ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

# ── Parse args ──
MONITORING=false
FORCE_BUILD=false
ENVIRONMENT="production"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --monitoring) MONITORING=true; shift ;;
        --build)      FORCE_BUILD=true; shift ;;
        --env)        ENVIRONMENT="$2"; shift 2 ;;
        *)            log_error "Unknown argument: $1"; exit 1 ;;
    esac
done

export ANSIQ_ENV="$ENVIRONMENT"

# ── Check .env ──
if [ ! -f .env ]; then
    log_warn "No .env file found. Copying .env.example..."
    if [ -f .env.example ]; then
        cp .env.example .env
        log_warn "Edit .env with your production secrets before deploying!"
    else
        log_error "No .env or .env.example found. Create one."
        exit 1
    fi
fi

# ── Create required directories ──
mkdir -p nginx/ssl monitoring/grafana-dashboards

# ── Generate self-signed SSL cert if none exists ──
if [ ! -f nginx/ssl/cert.pem ]; then
    log_info "Generating self-signed SSL certificate..."
    openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
        -keyout nginx/ssl/key.pem \
        -out nginx/ssl/cert.pem \
        -subj "/CN=ansiq.local" 2>/dev/null
    log_ok "Self-signed SSL cert generated"
fi

# ── Pull latest images ──
log_info "Pulling latest images..."
docker compose pull 2>/dev/null || true

# ── Build ──
BUILD_FLAG=""
if $FORCE_BUILD; then
    BUILD_FLAG="--build"
    log_info "Force rebuilding..."
fi

# ── Deploy ──
PROFILE_FLAG=""
if $MONITORING; then
    PROFILE_FLAG="--profile monitoring"
    log_info "Deploying with monitoring stack..."
fi

log_info "Deploying AnsiQ ($ENVIRONMENT)..."
docker compose $PROFILE_FLAG up -d $BUILD_FLAG

# ── Wait for health ──
log_info "Waiting for services to be healthy..."
for i in $(seq 1 30); do
    if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
        log_ok "API is healthy"
        break
    fi
    if [ "$i" -eq 30 ]; then
        log_warn "API health check timed out. Check logs: docker compose logs app"
    fi
    sleep 2
done

# ── Show status ──
echo ""
log_info "Deployment summary:"
docker compose ps

echo ""
log_info "Services:"
echo "  API:        http://localhost:8000"
echo "  Dashboard:  http://localhost:8501"
echo "  Docs:       http://localhost:8000/docs"
echo "  Health:     http://localhost:8000/health"
if $MONITORING; then
    echo "  Prometheus: http://localhost:9090"
    echo "  Grafana:    http://localhost:3000 (admin:${GRAFANA_PASSWORD:-admin})"
fi
echo ""
log_ok "Deployment complete!"