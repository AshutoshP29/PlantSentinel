"""Minimal client for the local Ollama server (embeddings + JSON chat).

All model names come from app.config. Tests replace these functions with fakes.
"""

import json

import httpx

from app.config import get_settings


def embed(texts: list[str], model: str | None = None) -> list[list[float]]:
    """Embed a batch of texts with the configured embedding model."""
    settings = get_settings()
    r = httpx.post(
        f"{settings.ollama_host}/api/embed",
        json={"model": model or settings.embed_model, "input": texts},
        timeout=120,
    )
    r.raise_for_status()
    return r.json()["embeddings"]


def chat_json(prompt: str, system: str | None = None, model: str | None = None) -> dict:
    """Ask the LLM for a strict JSON object (Ollama format="json")."""
    settings = get_settings()
    messages = [{"role": "system", "content": system}] if system else []
    messages.append({"role": "user", "content": prompt})
    r = httpx.post(
        f"{settings.ollama_host}/api/chat",
        json={
            "model": model or settings.llm_model,
            "messages": messages,
            "format": "json",
            "stream": False,
            "options": {"temperature": 0, "seed": 42},
        },
        timeout=120,
    )
    r.raise_for_status()
    return json.loads(r.json()["message"]["content"])
