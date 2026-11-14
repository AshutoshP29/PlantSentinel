import httpx
import pytest

from app.agent import llm
from app.config import get_settings


class _Resp:
    def __init__(self, models: list[str]) -> None:
        self._models = models

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return {"models": [{"name": m} for m in self._models]}


def test_check_ollama_reports_missing_and_handles_latest_suffix(monkeypatch) -> None:
    monkeypatch.setattr(
        httpx, "get", lambda *a, **k: _Resp(["qwen2.5:7b-instruct", "nomic-embed-text:latest"])
    )
    st = llm.check_ollama(["qwen2.5:7b-instruct", "nomic-embed-text", "qwen2.5vl:7b"])
    assert st.reachable
    assert st.missing == ["qwen2.5vl:7b"]
    assert not st.ready


def test_check_ollama_unreachable(monkeypatch) -> None:
    def boom(*a, **k):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "get", boom)
    st = llm.check_ollama()
    assert not st.reachable and st.error
    with pytest.raises(llm.LLMUnavailableError, match="OLLAMA_HOST"):
        llm.require_ollama()


def test_require_ollama_names_pull_command(monkeypatch) -> None:
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _Resp([]))
    with pytest.raises(llm.LLMUnavailableError, match=r"ollama pull qwen2\.5:7b-instruct"):
        llm.require_ollama()


def test_models_use_configured_local_host(monkeypatch) -> None:
    s = get_settings()
    monkeypatch.setattr(s, "ollama_host", "http://192.168.1.50:11434")
    monkeypatch.setattr(s, "llm_model", "qwen2.5:3b-instruct")
    chat = llm.get_chat_model(format={"type": "object"})
    assert chat.base_url == "http://192.168.1.50:11434"
    assert chat.model == "qwen2.5:3b-instruct"
    assert chat.format == {"type": "object"}
    assert chat.temperature == 0.0
    emb = llm.get_embeddings()
    assert emb.base_url == "http://192.168.1.50:11434"
    assert emb.model == "nomic-embed-text"


def test_ollama_host_from_env(monkeypatch) -> None:
    from app.config import Settings

    monkeypatch.setenv("OLLAMA_HOST", "http://172.20.0.1:11434")
    assert Settings().ollama_host == "http://172.20.0.1:11434"
