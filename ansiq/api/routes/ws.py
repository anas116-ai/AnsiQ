"""WebSocket route — real-time agent chat streaming.

Connects to ws://host:port/api/ws/agents/{agent_id}
and streams tokens as they arrive from the LLM.

Message format (client → server):
    {"message": "Hello, agent!"}

Message format (server → client):
    {"type": "token", "content": "Hello"}
    {"type": "done", "content": ""}
    {"type": "error", "content": "Error message"}
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ansiq.api.auth import _load_api_keys
from ansiq.api.state import get_app_state

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws/agents/{agent_id}")
async def agent_websocket(websocket: WebSocket, agent_id: str):
    """WebSocket endpoint for streaming agent chat.

    Accepts the connection, then listens for JSON messages
    and streams back tokens from the agent's LLM response.

    If API key auth is enabled, the client must pass the key
    as a query parameter: ws://host/ws/agents/{id}?api_key=sk-...
    """
    # Check API key via query parameter if auth is enabled
    keys = _load_api_keys()
    if keys:
        api_key = websocket.query_params.get("api_key", "")
        if api_key not in keys:
            await websocket.close(code=4001, reason="Unauthorized")
            return

    await websocket.accept()

    state = get_app_state()
    agent = state.agents.get(agent_id)

    if not agent:
        await websocket.send_json(
            {
                "type": "error",
                "content": f"Agent '{agent_id}' not found",
            }
        )
        await websocket.close(code=4004)
        return

    try:
        while True:
            # Receive message from client
            data = await websocket.receive_text()

            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                await websocket.send_json(
                    {
                        "type": "error",
                        "content": "Invalid JSON",
                    }
                )
                continue

            message = payload.get("message", "").strip()
            if not message:
                await websocket.send_json(
                    {
                        "type": "error",
                        "content": "Message is required",
                    }
                )
                continue

            context = payload.get("context")

            # Stream the response token by token
            try:
                async for token in await agent.chat(message, context=context, stream=True):
                    await websocket.send_json(
                        {
                            "type": "token",
                            "content": token,
                        }
                    )

                await websocket.send_json(
                    {
                        "type": "done",
                        "content": "",
                    }
                )
            except Exception as e:
                logger.error("WebSocket agent chat failed: %s", e)
                await websocket.send_json(
                    {
                        "type": "error",
                        "content": str(e),
                    }
                )

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected for agent: %s", agent_id)
    except Exception as e:
        logger.error("WebSocket error for agent '%s': %s", agent_id, e)
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
