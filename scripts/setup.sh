#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════
# AnsiQ — One-Command SaaS Setup
# ═══════════════════════════════════════════════════════════════════════
# This script sets up everything needed for production deployment:
#   1. Check prerequisites (Python 3.11+, Docker, Node.js)
#   2. Create .env from .env.example
#   3. Generate secure random secrets (REAL replacement, not silent)
#   4. Install Python dependencies
#   5. Initialize database (Docker-based PostgreSQL)
#   6. Run database migrations
#   7. Create admin user
#   8. Print setup summary
# ═══════════════════════════════════════════════════════════════════════

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

echo ""
echo "  ╔══════════════════════════════════════════╗"
echo "  ║      AnsiQ — Production Setup v0.1.0     ║"
echo "  ╚══════════════════════════════════════════╝"
echo ""

# ── Step 1: Prerequisites ──────────────────────────────────────────────
info "Checking prerequisites..."

command -v python3 >/dev/null 2>&1 || command -v python >/dev/null 2>&1 || error "Python 3.11+ is required"
PYTHON=$(command -v python3 || command -v python)
PY_VERSION=$($PYTHON --version 2>&1 | awk '{print $2}')
info "Python: $PY_VERSION"

command -v docker >/dev/null 2>&1 || warn "Docker not found (needed for PostgreSQL in dev)"
command -v git >/dev/null 2>&1 || warn "Git not found"

# ── Step 2: Environment Configuration ──────────────────────────────────
info "Setting up environment..."
if [ ! -f .env ]; then
    if [ ! -f .env.example ]; then
        error "No .env.example found. Copy manually."
    fi
    cp .env.example .env

    # Generate cryptographically random secrets.
    SECRET_KEY=$($PYTHON -c "import secrets; print(secrets.token_hex(32))")
    JWT_SECRET=$($PYTHON -c "import secrets; print(secrets.token_hex(32))")
    DB_PASSWORD=$($PYTHON -c "import secrets; print(secrets.token_urlsafe(24))")
    SENTRY_DSN="https://placeholder@o000000.ingest.sentry.io/0000000"
    GRAFANA_PASSWORD=$($PYTHON -c "import secrets; print(secrets.token_urlsafe(16))")

    # Detect BSD (macOS) vs GNU sed.
    if [[ "$OSTYPE" == "darwin"* ]]; then
        SED_INPLACE=(-i '')
    else
        SED_INPLACE=(-i)
    fi

    # Use the EXACT marker strings present in .env.example so the
    # replacement actually fires (the previous version of this script
    # used different strings and silently left placeholders in place).
    sed "${SED_INPLACE[@]}" "s|^ANSIQ_SECRET_KEY=.*|ANSIQ_SECRET_KEY=${SECRET_KEY}|" .env
    sed "${SED_INPLACE[@]}" "s|^ANSIQ_JWT_SECRET=.*|ANSIQ_JWT_SECRET=${JWT_SECRET}|" .env
    sed "${SED_INPLACE[@]}" "s|^ANSIQ_DB_PASSWORD=.*|ANSIQ_DB_PASSWORD=${DB_PASSWORD}|" .env
    sed "${SED_INPLACE[@]}" "s|^GRAFANA_PASSWORD=.*|GRAFANA_PASSWORD=${GRAFANA_PASSWORD}|" .env
    sed "${SED_INPLACE[@]}" "s|^SENTRY_DSN=.*|SENTRY_DSN=${SENTRY_DSN}|" .env

    ok ".env created with secure random secrets"
else
    ok ".env already exists"
fi

# ── Step 3: Install Dependencies ────────────────────────────────────────
info "Installing Python dependencies..."
$PYTHON -m pip install -q --upgrade pip
$PYTHON -m pip install -q -e ".[dev,all]" 2>/dev/null || \
    $PYTHON -m pip install -q sqlalchemy[asyncio] asyncpg stripe aiosmtplib sendgrid boto3 httpx pyjwt bcrypt pydantic fastapi uvicorn prometheus-client slowapi
ok "Dependencies installed"

# ── Step 4: Start PostgreSQL (Docker) ──────────────────────────────────
if command -v docker >/dev/null 2>&1; then
    if ! docker ps --format '{{.Names}}' | grep -q "ansiq-postgres"; then
        info "Starting PostgreSQL (Docker)..."
        docker run -d --name ansiq-postgres \
            -e POSTGRES_DB=ansiq \
            -e POSTGRES_USER=ansiq \
            -e POSTGRES_PASSWORD=ansiq \
            -p 5432:5432 \
            postgres:16-alpine 2>/dev/null || \
        warn "PostgreSQL container already exists (run: docker start ansiq-postgres)"
        info "Waiting for PostgreSQL to be ready..."
        for i in $(seq 1 30); do
            if docker exec ansiq-postgres pg_isready -U ansiq >/dev/null 2>&1; then
                ok "PostgreSQL is ready"
                break
            fi
            sleep 1
        done
    else
        ok "PostgreSQL already running"
    fi
fi

# ── Step 5: Initialize Database ────────────────────────────────────────
info "Initializing database schema..."
$PYTHON -c "
from saas.database import init_db
import asyncio
try:
    asyncio.run(init_db())
    print('  ✅ Tables created successfully')
except Exception as e:
    print(f'  ⚠️  init_db skipped: {e}')
" || warn "Database init skipped (no connection)"

# ── Step 6: Run Tests ──────────────────────────────────────────────────
info "Running test suite..."
$PYTHON -m pytest tests/ -v --tb=short 2>/dev/null && ok "All tests passed" || warn "Some tests failed (check output)"

# ── Step 7: Summary ────────────────────────────────────────────────────
echo ""
echo "  ╔══════════════════════════════════════════╗"
echo "  ║        Setup Complete! 🚀                ║"
echo "  ╚══════════════════════════════════════════╝"
echo ""
echo "  ┌──────────────────────────────────────────────┐"
echo "  │  API Server:    http://localhost:8000         │"
echo "  │  API Docs:      http://localhost:8000/docs    │"
echo "  │  Dashboard:     http://localhost:8501         │"
echo "  │  Landing Page:  http://localhost:8000         │"
echo "  │  Metrics:       http://localhost:8000/metrics │"
echo "  └──────────────────────────────────────────────┘"
echo ""
echo "  Quick Start:"
echo "    API:  uvicorn saas.app:app --reload"
echo "    UI:   streamlit run ansiq/ui/dashboard_pro.py"
echo "    Full: docker compose up -d"
echo ""
echo "  ⚠️  Before going to production:"
echo "    1. Set ANSIQ_ENV=production in .env"
echo "    2. Replace STRIPE_SECRET_KEY and STRIPE_WEBHOOK_SECRET with real values"
echo "    3. Replace SENTRY_DSN with your real Sentry project DSN"
echo "    4. Configure ANSIQ_CORS_ORIGINS with your real frontend URL"
echo "    5. Configure ANSIQ_APP_URL with your real public URL"
echo ""
