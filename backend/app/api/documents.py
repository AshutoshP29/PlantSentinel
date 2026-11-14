"""Generated documents: work orders (.docx) and the bad-actor report (.xlsx)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.agent.tools import ToolError, create_bad_actor_report, create_work_order
from app.api import agent as agent_api
from app.docgen.documents import MEDIA_TYPES, get_document, list_documents

router = APIRouter(prefix="/documents", tags=["documents"])


class WorkOrderRequest(BaseModel):
    tag: str = Field(min_length=2, max_length=20)
    issue: str | None = Field(None, max_length=300)
    priority: str | None = None
    requested_by: str = Field("PlantSentinel", max_length=80)


class ReportRequest(BaseModel):
    top_n: int = Field(20, ge=1, le=100)
    requested_by: str = Field("PlantSentinel", max_length=80)


def _public(item: dict) -> dict:
    return {k: v for k, v in item.items() if k not in {"unsupported_items_removed", "method"}}


@router.get("")
def documents() -> list[dict]:
    return list_documents()


@router.post("/work-order")
def new_work_order(req: WorkOrderRequest) -> dict:
    """Draft a work order for a tag (manual RAG + one LLM call + .docx). Returns DocumentItem."""
    ctx = agent_api.make_context(user=req.requested_by)
    try:
        return _public(create_work_order(ctx, req.tag, req.issue, req.priority, req.requested_by))
    except ToolError as exc:
        raise HTTPException(422, str(exc)) from exc
    finally:
        ctx.conn.close()


@router.post("/bad-actor-report")
def new_bad_actor_report(req: ReportRequest | None = None) -> dict:
    req = req or ReportRequest()
    ctx = agent_api.make_context(user=req.requested_by)
    try:
        return _public(create_bad_actor_report(ctx, req.top_n, req.requested_by))
    finally:
        ctx.conn.close()


@router.get("/{doc_id}/download")
def download(doc_id: str) -> FileResponse:
    found = get_document(doc_id)
    if found is None:
        raise HTTPException(404, "Document not found")
    item, path = found
    return FileResponse(
        path,
        media_type=MEDIA_TYPES.get(path.suffix, "application/octet-stream"),
        filename=item["file_name"],
    )
