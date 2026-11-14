"""Offline fakes for agent / RAG tests: no Ollama, no GPU, no ChromaDB server needed."""

from __future__ import annotations

import hashlib
import math
import re
import sqlite3
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pandas as pd
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from app.agent.rag import ManualStore
from app.agent.tools import AgentContext
from app.db import connect, init_db

ROOT = Path(__file__).resolve().parents[2]
SYNTHETIC = ROOT / "data" / "synthetic"
MANUALS = ROOT / "data" / "docs" / "manuals"


class ScriptedChatModel(BaseChatModel):
    """Returns pre-scripted messages in order and records every prompt it receives."""

    responses: list[Any]
    calls: list[list[BaseMessage]] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> ScriptedChatModel:
        return self

    def _generate(self, messages: list[BaseMessage], *a: Any, **kw: Any) -> ChatResult:
        self.calls.append(messages)
        if not self.responses:
            raise AssertionError("ScriptedChatModel ran out of responses")
        nxt = self.responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        msg = nxt if isinstance(nxt, AIMessage) else AIMessage(content=str(nxt))
        return ChatResult(generations=[ChatGeneration(message=msg)])


def tool_call(name: str, args: dict, call_id: str | None = None) -> AIMessage:
    return AIMessage(
        content="", tool_calls=[{"name": name, "args": args, "id": call_id or f"c_{name}"}]
    )


class HashEmbedder:
    """Deterministic bag-of-words embedding: texts sharing words are close in cosine space."""

    dim = 512

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        for w in re.findall(r"[a-z0-9]+", text.lower()):
            if len(w) > 2:
                v[int(hashlib.md5(w.encode()).hexdigest(), 16) % self.dim] += 1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


class MemoryCollection:
    """The subset of the chromadb Collection API that ManualStore uses (cosine space)."""

    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}

    @staticmethod
    def _match(meta: dict, where: dict | None) -> bool:
        return not where or all(meta.get(k) == v for k, v in where.items())

    def count(self) -> int:
        return len(self.rows)

    def add(self, ids, documents, metadatas, embeddings) -> None:
        for i, d, m, e in zip(ids, documents, metadatas, embeddings, strict=True):
            if i in self.rows:
                raise ValueError(f"duplicate id {i}")
            self.rows[i] = {"doc": d, "meta": m, "emb": e}

    def get(self, where=None, limit=None, include=None) -> dict:
        hits = [(i, r) for i, r in self.rows.items() if self._match(r["meta"], where)][:limit]
        return {"ids": [i for i, _ in hits], "metadatas": [r["meta"] for _, r in hits]}

    def delete(self, where=None) -> None:
        for i in [i for i, r in self.rows.items() if self._match(r["meta"], where)]:
            del self.rows[i]

    def query(self, query_embeddings, n_results, where=None, include=None) -> dict:
        q = query_embeddings[0]
        scored = sorted(
            (1 - sum(a * b for a, b in zip(q, r["emb"], strict=True)), i, r)
            for i, r in self.rows.items()
            if self._match(r["meta"], where)
        )[:n_results]
        return {
            "ids": [[i for _, i, _ in scored]],
            "documents": [[r["doc"] for *_, r in scored]],
            "metadatas": [[r["meta"] for *_, r in scored]],
            "distances": [[d for d, *_ in scored]],
        }


def memory_store() -> ManualStore:
    return ManualStore(MemoryCollection(), HashEmbedder())


def seeded_conn() -> sqlite3.Connection:
    conn = connect(":memory:")
    init_db(conn)
    pd.read_csv(SYNTHETIC / "assets.csv").to_sql("assets", conn, if_exists="append", index=False)
    pd.read_csv(SYNTHETIC / "work_orders.csv").to_sql(
        "work_orders", conn, if_exists="append", index=False
    )
    return conn


def make_context(
    tmp_path: Path,
    store: ManualStore | None = None,
    llm_factory: Callable[..., BaseChatModel] | None = None,
) -> AgentContext:
    def no_llm(**_: Any) -> BaseChatModel:
        raise AssertionError("this test should not call the recommendation LLM")

    return AgentContext(
        conn=seeded_conn(),
        store_factory=(lambda: store) if store else memory_store,
        llm_factory=llm_factory or no_llm,
        outputs_dir=tmp_path / "outputs",
    )


P101_INSPECTION = {
    "tag": "P-101",
    "date": "2026-11-02",
    "inspector": "R. Iyer",
    "report_no": "IR-2026-118",
    "findings": [
        {
            "item": "Mechanical seal",
            "result": "Leakage at gland, 20 drops/min",
            "flagged": True,
            "page": 1,
        },
        {
            "item": "Coupling alignment",
            "result": "Misalignment observed: 0.3 mm",
            "flagged": True,
            "page": 2,
        },
        {"item": "Bearing housing temperature", "result": "68 degC", "flagged": False, "page": 2},
    ],
    "summary": "Seal leaking; coupling misaligned.",
    "pages": 2,
    "file_name": "P-101_inspection.pdf",
}


def add_inspection(conn: sqlite3.Connection, extract: dict | None = None) -> str:
    """Insert an inspection row like the scan pipeline would. Returns its id."""
    import json

    ex = extract or P101_INSPECTION
    iid = f"INSP-{ex['tag'].replace('-', '')}-{ex['date'].replace('-', '')}"
    conn.execute(
        "INSERT INTO inspections(id, tag, date, file_path, raw_text, extracted_json) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            iid,
            ex["tag"],
            ex["date"],
            f"data/scans/{ex['file_name']}",
            "[page 1]\nSeal leakage at gland\n\n[page 2]\nMisalignment observed: 0.3 mm",
            json.dumps(ex),
        ),
    )
    conn.commit()
    return iid
