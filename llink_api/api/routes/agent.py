"""Point d'entrée explicite du nouvel agent Llink Work."""

from typing import Any

from fastapi import APIRouter, Depends, Request

from llink_api.database import get_db
from llink_api.schemas import ChatPayload
from llink_api.security import get_optional_user
from llink_api.services.work_agent import (\n    AGENT_PROTOCOL_VERSION, MAX_AGENT_SECONDS, MAX_MODEL_TURNS, MAX_TOOL_CALLS,\n    _available_tool_definitions, work_agent_response,\n)

router = APIRouter()



@router.get("/api/work/agent/status")
async def work_agent_status(
    user: dict = Depends(get_optional_user),
):
    """Expose la version du protocole et les outils réellement disponibles pour cette session."""
    definitions = _available_tool_definitions(user)
    tool_names = [
        item["function"]["name"]
        for item in definitions
        if item.get("type") == "function" and isinstance(item.get("function"), dict)
    ]
    return {
        "agent": "llink-work",
        "version": AGENT_PROTOCOL_VERSION,
        "protocol": "native_function_calling",
        "tools": tool_names,
        "limits": {
            "model_turns": MAX_MODEL_TURNS,
            "tool_calls": MAX_TOOL_CALLS,
            "seconds": MAX_AGENT_SECONDS,
        },
    }

@router.post("/api/work/agent")
async def run_work_agent(
    payload: ChatPayload,
    request: Request,
    user: dict = Depends(get_optional_user),
    db: Any | None = Depends(get_db),
):
    payload.mode = "work"
    return await work_agent_response(payload, request, user, db)
