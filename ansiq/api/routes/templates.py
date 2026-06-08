"""Template routes — list and apply pre-built agent templates.

Templates provide curated agent configurations that users can
browse and instantiate with a single API call.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ansiq.api.models import AgentResponse
from ansiq.api.state import get_app_state
from ansiq.api.templates import (
    AgentTemplate,
    create_agent_from_template,
    get_template,
    get_templates,
    templates_by_category,
)

router = APIRouter()


@router.get("", response_model=list[AgentTemplate])
async def list_templates(
    category: str | None = Query(None, description="Filter by category"),
):
    """List all available agent templates, optionally filtered by category."""
    if category:
        return templates_by_category(category)
    return get_templates()


@router.get("/{template_id}", response_model=AgentTemplate)
async def get_template_by_id(template_id: str):
    """Get a specific template by its ID."""
    template = get_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")
    return template


@router.post("/{template_id}/create", response_model=AgentResponse, status_code=201)
async def create_from_template(
    template_id: str,
    override_role: str | None = None,
    override_goal: str | None = None,
    override_model: str | None = None,
):
    """Create an agent from a template, with optional field overrides.

    Uses the template's curated role, goal, backstory, suggested model,
    temperature, and tools. Override params allow customizing key fields.
    """
    config = create_agent_from_template(
        template_id,
        override_role=override_role,
        override_goal=override_goal,
        override_model=override_model,
    )
    if not config:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")

    from ansiq.core.agent import Agent, AgentConfig, AgentIdentity

    identity = AgentIdentity(
        role=config["role"],
        goal=config["goal"],
        backstory=config.get("backstory", ""),
    )
    agent_config = AgentConfig(
        identity=identity,
        llm_provider=config.get("llm_provider", "openai"),
        llm_model=config.get("llm_model", "gpt-4o"),
        temperature=config.get("temperature", 0.7),
    )
    agent = Agent(identity=identity, config=agent_config)
    agent_id = config["role"].lower().replace(" ", "_")

    state = get_app_state()
    state.add_agent(agent_id, agent)

    return AgentResponse(
        id=agent_id,
        role=identity.role,
        goal=identity.goal,
        backstory=identity.backstory,
        llm_provider=config.get("llm_provider", "openai"),
        llm_model=agent_config.llm_model,
        tools_count=len(config.get("tools", [])),
        skills_count=0,
        memory_enabled=False,
    )
