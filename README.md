# AnsiQ — Intelligent Agent Orchestration Framework

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python Version](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/)
[![CI](https://github.com/anas116-ai/AnsiQ/actions/workflows/ci.yml/badge.svg)](https://github.com/anas116-ai/AnsiQ/actions/workflows/ci.yml)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)
[![Pytest](https://img.shields.io/badge/tests-787%20passing-brightgreen)](https://github.com/anas116-ai/AnsiQ/tree/main/tests)

**AnsiQ** is a production-ready, unified open-source framework that combines **multi-agent orchestration**, **persistent memory**, **autonomous skill learning**, **cross-platform messaging**, **SaaS API**, and **universal LLM support** — including local models via Ollama, cloud APIs (OpenAI, Anthropic), and HuggingFace.

> 🏢 **Production SaaS included** — Full multi-tenant API with Stripe billing, MFA, RBAC, audit logging, webhooks, and PostgreSQL-backed persistence.

---

## Features

### 🧠 Multi-Agent Orchestration
- **Pipeline Process** — Sequential task execution with context passing
- **Council Process** — Hierarchical coordination with a manager agent
- **Event-Driven Flows** — Decorator-based workflow engine (`@start`, `@listen`, `@router`)
- **DAG Orchestrator** — Parallel task execution with dependency resolution
- **Swarm Intelligence** — Agent voting, debating, and consensus mechanisms
- **State Management** — Type-safe Pydantic state with snapshot/rollback

### 🤖 Universal LLM Support
- **Local Models** — Ollama (no API key needed)
- **Cloud APIs** — OpenAI, Anthropic Claude, OpenRouter
- **Open Source** — HuggingFace Inference API
- **Smart Router** — Auto-selects best model based on task complexity
- **Automatic Fallback** — Graceful degradation if provider fails
- **Custom Providers** — Extend via `LLMProvider` abstract base class

### 💾 Persistent Memory
- **FTS5 Full-Text Search** — SQLite-based fast memory retrieval
- **Episodic Memory** — Timeline of experiences with LLM-summarized compressions
- **User Profiles** — Learn preferences and behavior patterns over time
- **Tag-Based Organization** — Categorize and filter memories

### 🛠 Tool System
- **Auto-Discovery** — `@ansiq_tool` decorator for automatic registration
- **Built-in Tools** — File operations, web search/fetch, code execution
- **Tool Registry** — Global registry for discoverable tools
- **Custom Tools** — Extend via `BaseTool` abstract class

### 🏢 SaaS API (Production-Ready)
- **Multi-Tenant** — Organizations, workspaces, role-based access control
- **Authentication** — JWT tokens, refresh token rotation, MFA (TOTP)
- **Billing** — Stripe integration with subscription management
- **API Keys** — Key generation, scoping, and revocation
- **Webhooks** — Event delivery with HMAC-SHA256 signing
- **Audit Logging** — Full event trail for compliance (GDPR-ready)
- **Rate Limiting** — Per-tenant rate limits with slowapi
- **Monitoring** — Prometheus metrics, Sentry error tracking, structured logging
- **Email** — SMTP / SendGrid / AWS SES support

### 📡 Cross-Platform Messaging
- **Telegram** — Full bot API integration
- **Discord** — Bot with message content intent
- **Slack** — RTM and Web API integration
- **Unified Interface** — Common `Message` model across platforms

### 🔒 Execution Environments
- **Local** — Subprocess execution with timeout
- **Docker** — Isolated container execution
- **SSH** — Remote machine execution

### Additional Features
- **Skill System** — LLM generates skills from natural language descriptions
- **YAML Configuration** — Declarative agent/crew/task setup
- **CLI** — Rich terminal interface with chat, memory, and skill management
- **Scheduler** — Cron-based task scheduling with persistence
- **Vector Database** — ChromaDB integration for embeddings storage
- **Embeddings** — Sentence-transformers for local embedding generation
- **Evaluation** — A/B testing, benchmarks, quality metrics

---

## Quick Start

### Installation

```bash
# Clone and install
git clone https://github.com/anas116-ai/AnsiQ.git
cd AnsiQ

# Install with pip (recommended)
pip install -e .

# Install with all extras
pip install -e ".[all]"

# Install specific extras
pip install -e ".[saas,openai]"
pip install -e ".[embeddings,vectordb]"
```

### Basic Usage

```python
from ansiq.core.agent import Agent, AgentIdentity
from ansiq.core.crew import Crew, ProcessType
from ansiq.core.task import Task

# Create agents
researcher = Agent(
    identity=AgentIdentity(
        role="Senior Researcher",
        goal="Find comprehensive information on any topic",
        backstory="Expert researcher with years of experience.",
    ),
)

writer = Agent(
    identity=AgentIdentity(
        role="Technical Writer",
        goal="Create clear, engaging content",
        backstory="Professional writer specializing in technical topics.",
    ),
)

# Define tasks
research = Task(
    description="Research the topic: {topic}",
    expected_output="Research summary",
    agent=researcher,
)

write = Task(
    description="Write article based on research findings",
    expected_output="Polished article",
    agent=writer,
    context=[research],
)

# Run the crew
crew = Crew(
    agents=[researcher, writer],
    tasks=[research, write],
    process=ProcessType.PIPELINE,
)

result = await crew.kickoff(inputs={"topic": "AI Agents"})
print(result.raw_output)
```

### CLI Usage

```bash
# Start interactive chat
ansiq chat

# Chat with local model
ansiq chat --local

# Run a crew from config
ansiq run config/research_crew.yaml -i topic="AI" depth=detailed

# Manage agents
ansiq agent create --role "Researcher" --goal "Find information" --model gpt-4o

# Browse memory
ansiq memory list
ansiq memory search "machine learning"
```

---

## SaaS API (Docker Deployment)

### Quick Start with Docker

```bash
docker-compose up -d
```

This starts:
- **FastAPI app** on `http://localhost:8000`
- **PostgreSQL** on port `5432`
- **Redis** on port `6379`
- **Prometheus** on port `9090`
- **Grafana** on port `3000`

### API Endpoints

| Category | Endpoints | Auth Required |
|----------|-----------|---------------|
| Health | `GET /health`, `GET /ready`, `GET /version` | ❌ |
| Auth | `POST /api/v1/auth/signup`, `/login`, `/refresh`, `/logout` | ❌ (except `/logout`) |
| User | `GET /api/v1/auth/me` | ✅ |
| MFA | `POST /api/v1/account/mfa/enable`, `/confirm`, `/disable` | ✅ |
| GDPR | `GET /api/v1/account/me/export`, `POST /.../delete` | ✅ |
| Agents | `CRUD /api/v1/agents` | ✅ |
| Crews | `CRUD /api/v1/crews` | ✅ |
| Tasks | `CRUD /api/v1/tasks` | ✅ |
| Billing | `GET /api/v1/billing/subscription`, `/invoices` | ✅ |
| Webhooks | `CRUD /api/v1/webhooks` + event delivery | ✅ |
| Audit | `GET /api/v1/audit-logs` | ✅ (admin only) |
| Workspaces | `CRUD /api/v1/workspaces` | ✅ |
| API Keys | `CRUD /api/v1/api-keys` | ✅ |
| Members | `GET/PATCH /api/v1/members` | ✅ |

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ANSIQ_ENV` | `development` | Environment mode |
| `ANSIQ_DB_HOST` | `localhost` | PostgreSQL host |
| `ANSIQ_DB_PORT` | `5432` | PostgreSQL port |
| `ANSIQ_DB_NAME` | `ansiq` | Database name |
| `ANSIQ_DB_USER` | `ansiq` | Database user |
| `ANSIQ_DB_PASSWORD` | `ansiq` | Database password |
| `ANSIQ_JWT_SECRET` | (auto-generated) | JWT signing key |
| `ANSIQ_SECRET_KEY` | (auto-generated) | App encryption key |
| `ANSIQ_CORS_ORIGINS` | `*` | Allowed CORS origins |
| `ANSIQ_APP_URL` | `http://localhost:8000` | Public app URL |
| `STRIPE_SECRET_KEY` | — | Stripe API key |
| `STRIPE_WEBHOOK_SECRET` | — | Stripe webhook secret |
| `SENTRY_DSN` | — | Sentry error tracking DSN |

---

## YAML Configuration

```yaml
# config/research_crew.yaml
crew:
  name: research_crew
  process: pipeline
  agents:
    researcher:
      role: Senior Researcher
      goal: Find comprehensive information
      backstory: Expert researcher
      llm_provider: ollama
      llm_model: llama3.2
  tasks:
    - description: Research {topic}
      expected_output: Summary
      agent: researcher
```

---

## Architecture

```
ansiq/                      # Core framework
├── core/                   # Agent, Task, Crew, Flow, State
├── llm/                    # LLM providers + smart router
├── memory/                 # FTS5, episodic, profiles
├── tools/                  # Tool system + auto-discovery
├── skills/                 # Skill learning system
├── orchestration/          # DAG + parallel executor
├── swarm/                  # Consensus, debate, intelligence
├── cli/                    # Rich terminal interface
├── gateway/                # Telegram, Discord, Slack
├── execution/              # Local, Docker, SSH
├── scheduler/              # Cron-based scheduling
├── config/                 # YAML parser
├── embeddings/             # Sentence-transformers
├── vectordb/               # ChromaDB provider
├── auth/                   # RBAC, audit logging
├── api/                    # Server, tenant, keys
├── analytics/              # Cost tracking, billing
├── evaluation/             # A/B testing, benchmarks
├── plugins/                # Plugin system
├── knowledge/              # Knowledge engine
├── sandbox/                # Docker sandboxing
├── ui/                     # Dashboard components
└── brain/                  # Reasoning engine

saas/                       # Multi-tenant SaaS API
├── app.py                  # FastAPI application
├── auth.py                 # JWT, passwords, MFA
├── database.py             # PostgreSQL + SQLAlchemy
├── models.py               # ORM models
├── billing.py              # Stripe integration
├── email.py                # SMTP/SendGrid/SES
├── webhooks.py             # Event delivery
├── config.py               # SaaS configuration
└── routes/                 # API route handlers
    ├── auth.py, agents.py, crews.py, tasks.py
    ├── account.py, billing.py, api.py
    └── ws.py               # WebSocket support
```

---

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run linter
ruff check saas/ ansiq/
ruff check . --ignore E501  # Full project

# Run format check
ruff format --check saas/ ansiq/

# Run tests
pytest tests/ -v

# Run specific test files
pytest tests/test_saas_routes.py tests/test_core.py -v

# Run audit
python check_audit.py

# Run security scan
bandit -r saas/ -ll

# Type check
mypy saas/ --ignore-missing-imports
```

### Test Suite

- **787 tests** across 30+ test files
- In-memory SQLite for fast, isolated testing
- Mocked LLM providers (no API calls needed)
- CI pipeline: lint → typecheck → security → tests → Docker build

---

## Extras

| Extra | Install | Required For |
|-------|---------|-------------|
| `openai` | `pip install 'ansiq[openai]'` | OpenAI API |
| `anthropic` | `pip install 'ansiq[anthropic]'` | Claude API |
| `huggingface` | `pip install 'ansiq[huggingface]'` | HuggingFace API |
| `saas` | `pip install 'ansiq[saas]'` | Multi-tenant SaaS API |
| `embeddings` | `pip install 'ansiq[embeddings]'` | Local embeddings |
| `vectordb` | `pip install 'ansiq[vectordb]'` | ChromaDB vector store |
| `telegram` | `pip install 'ansiq[telegram]'` | Telegram bot |
| `discord` | `pip install 'ansiq[discord]'` | Discord bot |
| `slack` | `pip install 'ansiq[slack]'` | Slack bot |
| `docker` | `pip install 'ansiq[docker]'` | Docker execution |
| `ssh` | `pip install 'ansiq[ssh]'` | SSH execution |
| `monitoring` | `pip install 'ansiq[monitoring]'` | Prometheus + psutil |
| `all` | `pip install 'ansiq[all]'` | Everything |
| `dev` | `pip install 'ansiq[dev]'` | Development tools |

---

## Requirements

- **Python 3.12+**
- For SaaS API: PostgreSQL, Redis
- For local models: [Ollama](https://ollama.ai/) with pulled models
- For Docker execution: Docker daemon
- For messaging gateways: Bot tokens (Telegram, Discord, Slack)

---

## License

MIT License — see [LICENSE](LICENSE) for details.

---

## Project Status

✅ **Production Ready** — All core features implemented, tested, and documented.
- 787 passing tests, zero lint errors
- Full CI/CD pipeline with GitHub Actions
- Docker Compose for one-command deployment
- Multi-tenant SaaS API with billing, auth, monitoring
- GDPR-compliant data handling with export and deletion
- OpenTelemetry-ready logging and metrics
