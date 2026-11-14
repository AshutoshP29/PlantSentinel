"""All runtime configuration. Every value is overridable via env var (or a .env file)."""

from datetime import date
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Ollama. Local dev: host app on localhost. Docker: the `ollama` service on the
    # internal network (docker-compose sets OLLAMA_HOST=http://ollama:11434).
    ollama_host: str = "http://localhost:11434"
    # Defaults sized for a 6 GB GPU (fully GPU-resident). 8+ GB: qwen2.5:7b-instruct and
    # qwen2.5vl:7b. Faster fallback: qwen2.5:3b-instruct. See scripts/benchmark_models.py.
    llm_model: str = "qwen2.5:7b-instruct-q3_K_M"
    vision_model: str = "qwen2.5vl:3b"
    embed_model: str = "nomic-embed-text"
    # Optional separate model for failure-mode naming (quality matters more than speed there;
    # 7b merges synonyms better: ARI 0.93 vs 0.87). Empty = use llm_model.
    naming_model: str = ""
    llm_temperature: float = 0.0
    llm_num_ctx: int = 8192
    llm_timeout_s: float = 180.0  # per request; first call also loads the model into VRAM
    llm_keep_alive_s: int = 1800  # keep the model loaded between requests

    # Agent / RAG
    agent_max_iterations: int = 8  # max agent->tools round trips per question
    chroma_collection: str = "manuals"
    rag_top_k: int = 5
    rag_chunk_chars: int = 900
    rag_chunk_overlap: int = 150
    rag_max_distance: float = 0.6  # cosine distance; weaker matches are dropped as irrelevant
    analysis_window_days: int = 180  # "recent" window for failure counts (bad-actor window)
    analysis_as_of: date | None = None  # pin "today" for analytics (demo); None = real date
    site_name: str = "Demo Refinery"  # shown on the dashboard

    # Storage
    data_dir: Path = REPO_ROOT / "data"
    models_dir: Path = REPO_ROOT / "models"
    db_path: Path = REPO_ROOT / "data" / "plantsentinel.db"
    chroma_dir: Path = REPO_ROOT / "data" / "chroma"
    manuals_dir: Path = REPO_ROOT / "data" / "docs" / "manuals"
    outputs_dir: Path = REPO_ROOT / "outputs"  # generated work orders (.docx)
    # When set, use a Chroma server (the `chroma` Compose service) instead of the embedded
    # store in chroma_dir.
    chroma_host: str | None = None
    chroma_port: int = 8000

    # Privacy: when true, any non-Ollama outbound HTTP must raise (used by offline-check)
    block_egress: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
