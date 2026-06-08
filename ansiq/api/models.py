"""Pydantic models for API request/response schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

# ── Health ──


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = ""
    uptime_seconds: float = 0.0


# ── Agents ──


class AgentCreateRequest(BaseModel):
    role: str = Field(..., min_length=1)
    goal: str = Field(..., min_length=1)
    backstory: str = ""
    llm_provider: str = "openai"
    llm_model: str = "gpt-4o"
    temperature: float = 0.7


class AgentResponse(BaseModel):
    id: str
    role: str
    goal: str
    backstory: str
    llm_provider: str
    llm_model: str
    tools_count: int = 0
    skills_count: int = 0
    memory_enabled: bool = False


class AgentListResponse(BaseModel):
    agents: list[AgentResponse]
    total: int


class AgentChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    context: str | None = None
    stream: bool = False


class AgentChatResponse(BaseModel):
    content: str
    model: str = ""
    finish_reason: str | None = None
    usage: dict[str, int] = Field(default_factory=dict)


class AgentRunRequest(BaseModel):
    task: str = Field(..., min_length=1)
    context: str | None = None
    stream: bool = False


# ── Crews ──


class CrewAgentRef(BaseModel):
    role: str
    goal: str = ""
    backstory: str = ""
    llm_provider: str = "openai"
    llm_model: str = "gpt-4o"


class CrewTaskRef(BaseModel):
    description: str = Field(..., min_length=1)
    expected_output: str = ""
    agent_role: str | None = None


class CrewCreateRequest(BaseModel):
    name: str = Field(..., min_length=1)
    agents: list[CrewAgentRef] = Field(..., min_length=1)
    tasks: list[CrewTaskRef] = Field(..., min_length=1)
    process: str = "pipeline"


class CrewResponse(BaseModel):
    id: str
    name: str
    agents_count: int
    tasks_count: int
    process: str


class CrewListResponse(BaseModel):
    crews: list[CrewResponse]
    total: int


class CrewRunRequest(BaseModel):
    inputs: dict[str, Any] = Field(default_factory=dict)


class CrewRunResponse(BaseModel):
    tasks_output: list[str]
    task_results: dict[str, Any]
    raw_output: str = ""


# ── Memory ──


class MemoryItem(BaseModel):
    rowid: int
    content: str = ""
    summary: str = ""
    timestamp: str = ""
    agent_id: str = ""
    tags: list[str] = Field(default_factory=list)


class MemoryListResponse(BaseModel):
    memories: list[MemoryItem]
    total: int


class MemorySearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    limit: int = 20


class MemoryStatsResponse(BaseModel):
    total_memories: int
    total_agents: int
    db_path: str = ""


# ── Knowledge ──


class KnowledgeSourceRequest(BaseModel):
    name: str = Field(..., min_length=1)
    source_type: str = "text"  # text, file, url
    content: str = ""  # for text sources
    url: str = ""  # for url sources
    file_path: str = ""  # for file sources


class KnowledgeSourceResponse(BaseModel):
    name: str
    source_type: str
    chunks_count: int = 0
    added: bool = False


class KnowledgeQueryRequest(BaseModel):
    query: str = Field(..., min_length=1)
    top_k: int = 3


class KnowledgeQueryResult(BaseModel):
    text: str
    source: str = ""
    score: float = 0.0
    chunk_index: int = 0


class KnowledgeQueryResponse(BaseModel):
    results: list[KnowledgeQueryResult]
    total: int


class KnowledgeStatsResponse(BaseModel):
    total_chunks: int
    total_sources: int
    vocabulary_size: int = 0
    embedded_chunks: int = 0


# ── Skills ──


class SkillResponse(BaseModel):
    name: str
    description: str = ""
    category: str = ""
    version: str = "1.0"


class SkillListResponse(BaseModel):
    skills: list[SkillResponse]
    total: int


class SkillCreateRequest(BaseModel):
    name: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    category: str = "custom"
    implementation: str | None = None


# ── Error ──


class ErrorResponse(BaseModel):
    detail: str
    error_code: str = "UNKNOWN"
    timestamp: float = 0.0
