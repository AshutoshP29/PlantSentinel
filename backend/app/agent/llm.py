"""Local Ollama access: model availability checks and LangChain model factories.

All inference goes to the Ollama server at `settings.ollama_host` (env: OLLAMA_HOST).
Nothing here talks to any hosted inference service.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import httpx
from langchain_ollama import ChatOllama, OllamaEmbeddings

from app.config import Settings, get_settings

log = logging.getLogger(__name__)


class LLMUnavailableError(RuntimeError):
    """Ollama is not reachable or a required model is not pulled."""


@dataclass
class OllamaStatus:
    reachable: bool
    host: str
    installed: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def ready(self) -> bool:
        return self.reachable and not self.missing


def _normalise(tag: str) -> str:
    """`nomic-embed-text` and `nomic-embed-text:latest` are the same model."""
    return tag if ":" in tag else f"{tag}:latest"


def required_models(settings: Settings | None = None) -> list[str]:
    s = settings or get_settings()
    return [s.llm_model, s.embed_model]


def check_ollama(
    models: list[str] | None = None, settings: Settings | None = None, timeout: float = 3.0
) -> OllamaStatus:
    """Ask the local Ollama server which models it has and which required ones are missing."""
    s = settings or get_settings()
    wanted = models if models is not None else required_models(s)
    try:
        resp = httpx.get(f"{s.ollama_host}/api/tags", timeout=timeout)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        return OllamaStatus(False, s.ollama_host, missing=list(wanted), error=str(exc))
    installed = sorted(m["name"] for m in resp.json().get("models", []))
    have = {_normalise(m) for m in installed}
    missing = [m for m in wanted if _normalise(m) not in have]
    return OllamaStatus(True, s.ollama_host, installed=installed, missing=missing)


def require_ollama(models: list[str] | None = None) -> OllamaStatus:
    """Like check_ollama but raises LLMUnavailableError with an actionable message."""
    status = check_ollama(models)
    if not status.reachable:
        raise LLMUnavailableError(
            f"Ollama is not reachable at {status.host} ({status.error}). "
            "Start Ollama, or set OLLAMA_HOST to the right URL."
        )
    if status.missing:
        pulls = "; ".join(f"ollama pull {m}" for m in status.missing)
        raise LLMUnavailableError(f"Missing Ollama model(s): {status.missing}. Run: {pulls}")
    return status


def _client_kwargs(s: Settings) -> dict:
    return {"timeout": s.llm_timeout_s}


def get_chat_model(
    *,
    model: str | None = None,
    temperature: float | None = None,
    format: str | dict | None = None,
) -> ChatOllama:
    """Chat model for the agent (tool calling) and for structured generation.

    `format="json"` forces JSON output; a JSON-schema dict makes Ollama constrain decoding to
    that schema (structured outputs), which is much more reliable with 7B models.
    """
    s = get_settings()
    return ChatOllama(
        model=model or s.llm_model,
        base_url=s.ollama_host,
        temperature=s.llm_temperature if temperature is None else temperature,
        num_ctx=s.llm_num_ctx,
        keep_alive=s.llm_keep_alive_s,
        format=format,
        client_kwargs=_client_kwargs(s),
    )


def get_embeddings(model: str | None = None) -> OllamaEmbeddings:
    s = get_settings()
    return OllamaEmbeddings(
        model=model or s.embed_model,
        base_url=s.ollama_host,
        keep_alive=s.llm_keep_alive_s,
        client_kwargs=_client_kwargs(s),
    )
