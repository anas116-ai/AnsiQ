"""REST API — HTTP interface for controlling AnsiQ remotely.

Start the server:
    ansiq serve          # Default: localhost:8000
    ansiq serve --port 8080 --host 0.0.0.0

Endpoints:
    GET    /api/health              → Server status
    POST   /api/agents              → Create agent
    GET    /api/agents              → List agents
    POST   /api/agents/{id}/chat    → Chat with agent
    POST   /api/agents/{id}/stream  → Stream chat via SSE
    POST   /api/agents/{id}/run     → Run task
    POST   /api/crews               → Create crew
    GET    /api/crews               → List crews
    POST   /api/crews/{id}/run      → Execute crew
    GET    /api/memory              → List memories
    POST   /api/memory/search       → Search memories
    GET    /api/memory/stats        → Memory statistics
    POST   /api/knowledge/sources   → Add knowledge source
    GET    /api/knowledge/sources   → List knowledge sources
    POST   /api/knowledge/query     → Query knowledge
    GET    /api/knowledge/stats     → Knowledge stats
    GET    /api/skills              → List skills
    POST   /api/skills              → Register skill
"""

from ansiq.api.server import create_app, run_server

__all__ = [
    "create_app",
    "run_server",
]
