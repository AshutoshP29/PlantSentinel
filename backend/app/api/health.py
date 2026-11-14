import httpx
from fastapi import APIRouter

from app.config import get_settings
from app.db import connect

router = APIRouter()


def ollama_reachable() -> bool:
    """True if the local Ollama server answers. Local call only."""
    try:
        return httpx.get(f"{get_settings().ollama_host}/api/tags", timeout=1.0).is_success
    except httpx.HTTPError:
        return False


@router.get("/health")
def health() -> dict:
    settings = get_settings()
    try:
        conn = connect(settings.db_path)
        try:
            conn.execute("SELECT 1")
        finally:
            conn.close()
        db_ok = True
    except Exception:
        db_ok = False
    return {"status": "ok" if db_ok else "degraded", "db": db_ok, "ollama": ollama_reachable()}
