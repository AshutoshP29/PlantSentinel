"""Agent endpoints: streamed chat (SSE), status, and work-order download."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from app.agent.graph import stream_agent
from app.agent.llm import check_ollama, get_chat_model
from app.agent.rag import ManualStore
from app.agent.tools import AgentContext
from app.config import get_settings
from app.db import connect
from app.docgen.work_order import safe_filename

log = logging.getLogger(__name__)
router = APIRouter(prefix="/agent", tags=["agent"])

DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=8000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=20)


@lru_cache
def _manual_store() -> ManualStore:
    return ManualStore.from_settings()


def make_context() -> AgentContext:
    s = get_settings()
    return AgentContext(
        conn=connect(s.db_path),
        store_factory=_manual_store,
        llm_factory=get_chat_model,
        outputs_dir=s.outputs_dir,
    )


@router.post("/chat")
async def chat(req: ChatRequest) -> EventSourceResponse:
    """Stream the agent run as server-sent events. Event names are graph.EVENT_TYPES."""

    async def events() -> AsyncIterator[dict]:
        ctx = make_context()
        try:
            async for ev in stream_agent(
                req.message, ctx, get_chat_model(), [t.model_dump() for t in req.history]
            ):
                yield {"event": ev["type"], "data": json.dumps(ev["data"], default=str)}
        finally:
            ctx.conn.close()

    return EventSourceResponse(events())


@router.get("/status")
def status() -> dict:
    """Ollama and model readiness plus the number of indexed manual chunks."""
    ollama = check_ollama()
    try:
        chunks, store_error = _manual_store().count(), None
    except Exception as exc:  # chroma not available / not initialised
        chunks, store_error = 0, str(exc)
    return {
        "ollama": {
            "reachable": ollama.reachable,
            "host": ollama.host,
            "missing_models": ollama.missing,
            "error": ollama.error,
        },
        "manual_chunks": chunks,
        "manual_store_error": store_error,
        "ready": ollama.ready and chunks > 0,
    }


@router.get("/work-orders/{filename}")
def download_work_order(filename: str) -> FileResponse:
    """Download a generated work order. Only plain .docx names inside outputs_dir."""
    if filename != safe_filename(filename) or not filename.endswith(".docx"):
        raise HTTPException(400, "Invalid file name")
    out_dir = get_settings().outputs_dir.resolve()
    path = (out_dir / filename).resolve()
    if path.parent != out_dir or not path.is_file():
        raise HTTPException(404, "Work order not found")
    return FileResponse(path, media_type=DOCX_MEDIA_TYPE, filename=filename)
