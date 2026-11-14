"""All runtime configuration. Every value is overridable via env var (or a .env file)."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Ollama (runs on the host; from Docker use http://host.docker.internal:11434)
    ollama_host: str = "http://localhost:11434"
    llm_model: str = "qwen2.5:7b-instruct"
    vision_model: str = "qwen2.5vl:7b"
    embed_model: str = "nomic-embed-text"

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
