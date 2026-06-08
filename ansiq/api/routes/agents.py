"""Agent management routes — create, list, chat, run, stream."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse

from ansiq.api.models import (
    AgentChatRequest,
    AgentChatResponse,
    AgentCreateRequest,
    AgentListResponse,
    AgentResponse,
    AgentRunRequest,
)
from ansiq.api.state import get_app_state

logger = logging.getLogger(__name__)

router = APIRouter()


def _agent_to_response(agent_id: str, agent: Any) -> AgentResponse:
    """Convert an Agent object to API response model."""
    return AgentResponse(
        id=agent_id,
        role=agent.identity.role,
        goal=agent.identity.goal,
        backstory=agent.identity.backstory,
        llm_provider=agent.config.llm_provider,
        llm_model=agent.config.llm_model,
        tools_count=len(agent.tools) if hasattr(agent, "tools") else 0,
        skills_count=len(agent.skills) if hasattr(agent, "skills") else 0,
        memory_enabled=agent.memory is not None,
    )


@router.post("", response_model=AgentResponse, status_code=201)
async def create_agent(req: AgentCreateRequest):
    """Create a new agent and add it to the shared state."""
    state = get_app_state()

    from ansiq.core.agent import Agent, AgentConfig, AgentIdentity

    identity = AgentIdentity(
        role=req.role,
        goal=req.goal,
        backstory=req.backstory,
    )
    config = AgentConfig(
        identity=identity,
        llm_provider=req.llm_provider,
        llm_model=req.llm_model,
        temperature=req.temperature,
    )

    agent = Agent(identity=identity, config=config)
    agent_id = req.role.lower().replace(" ", "_")

    state.add_agent(agent_id, agent)
    logger.info("Created agent: %s (%s)", agent_id, req.role)

    return _agent_to_response(agent_id, agent)


@router.get("", response_model=AgentListResponse)
async def list_agents():
    """List all agents in the shared state."""
    state = get_app_state()
    agents = [_agent_to_response(aid, agent) for aid, agent in state.agents.items()]
    return AgentListResponse(agents=agents, total=len(agents))


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(agent_id: str):
    """Get a specific agent by ID."""
    state = get_app_state()
    agent = state.agents.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    return _agent_to_response(agent_id, agent)


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(agent_id: str):
    """Delete an agent by ID."""
    state = get_app_state()
    if not state.remove_agent(agent_id):
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    logger.info("Deleted agent: %s", agent_id)


@router.post("/{agent_id}/chat", response_model=AgentChatResponse)
async def chat_with_agent(agent_id: str, req: AgentChatRequest):
    """Chat with an agent (non-streaming). Returns full response."""
    state = get_app_state()
    agent = state.agents.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    try:
        response = await agent.chat(req.message, context=req.context)
        return AgentChatResponse(
            content=response.content,
            model=response.model,
            finish_reason=response.finish_reason,
            usage={
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            },
        )
    except Exception as e:
        logger.error("Agent chat failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{agent_id}/stream")
async def stream_with_agent(agent_id: str, req: AgentChatRequest):
    """Chat with an agent via SSE streaming.

    Returns tokens as Server-Sent Events until completion.
    Each event has `data: <token>` and ends with `data: [DONE]`.
    """
    state = get_app_state()
    agent = state.agents.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    async def event_generator():
        try:
            async for token in await agent.chat(req.message, context=req.context, stream=True):
                yield {"event": "token", "data": token}
            yield {"event": "done", "data": "[DONE]"}
        except Exception as e:
            logger.error("Agent stream failed: %s", e)
            yield {"event": "error", "data": str(e)}

    return EventSourceResponse(event_generator())


@router.post("/{agent_id}/run", response_model=AgentChatResponse)
async def run_agent_task(agent_id: str, req: AgentRunRequest):
    """Run a task with an agent (non-streaming)."""
    state = get_app_state()
    agent = state.agents.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    try:
        response = await agent.run(req.task, context=req.context)
        return AgentChatResponse(
            content=response.content,
            model=response.model,
            finish_reason=response.finish_reason,
            usage={
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            },
        )
    except Exception as e:
        logger.error("Agent run failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
