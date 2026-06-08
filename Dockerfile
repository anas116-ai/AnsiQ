# ──────────────────────────────────────────────────────────────────────
# AnsiQ — Multi-stage Docker Build
# ──────────────────────────────────────────────────────────────────────
# Targets:
#   base       → Python 3.12 slim base with deps
#   production → FastAPI (uvicorn) for the SaaS API
#   dashboard  → Streamlit dashboard
# ──────────────────────────────────────────────────────────────────────

FROM python:3.12-slim AS base

LABEL maintainer="AnsiQ Team"
LABEL description="AnsiQ — Intelligent Agent Orchestration Platform"

# Prevent Python from writing .pyc files
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY pyproject.toml README.md ./
RUN pip install --upgrade pip setuptools wheel && \
    # NOTE: Only saas+monitoring extras in production. LLM providers (openai,\
    # anthropic, ollama) are excluded intentionally. If the API server needs\
    # to make direct LLM calls, add extras here (e.g. .[saas,monitoring,openai])\
    pip install ".[saas,monitoring]" uvicorn[standard] gunicorn

# ── Production API Server ──────────────────────────────────────────────
FROM base AS production

COPY . /app

# Create non-root user
RUN addgroup --system ansiq && adduser --system --ingroup ansiq ansiq && \
    chown -R ansiq:ansiq /app
USER ansiq

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "saas.app:app", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "4", "--proxy-headers", "--limit-max-requests", "10000"]

# ── Streamlit Dashboard ────────────────────────────────────────────────
FROM base AS dashboard

COPY . /app

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
  CMD curl -f http://localhost:8501 || exit 1

CMD ["streamlit", "run", "ansiq/ui/dashboard_pro.py", \
     "--server.port=8501", "--server.address=0.0.0.0", \
     "--server.enableCORS=false", "--server.enableXsrfProtection=false"]