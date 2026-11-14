"""All runtime configuration. Every value is overridable via env var (or a .env file)."""

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
    # Keep models in VRAM between requests (avoids reloads mid-demo).
    ollama_keep_alive: str = "30m"
    # Context window for chat calls; smaller = less VRAM.
    llm_num_ctx: int = 4096

    # Storage
    data_dir: Path = REPO_ROOT / "data"
    models_dir: Path = REPO_ROOT / "models"
    db_path: Path = REPO_ROOT / "data" / "plantsentinel.db"
    chroma_dir: Path = REPO_ROOT / "data" / "chroma"

    # Privacy: when true, any non-Ollama outbound HTTP must raise (used by offline-check)
    block_egress: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
