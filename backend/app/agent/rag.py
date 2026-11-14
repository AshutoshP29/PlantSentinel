"""Technical-manual RAG: clean -> chunk -> embed (local Ollama) -> ChromaDB -> cited retrieval.

Input is page-level text. Digital PDFs and Markdown/text manuals are read here; scanned
documents arrive as page text from the ingestion/OCR pipeline via `pages_from_records`.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel

from app.config import get_settings

log = logging.getLogger(__name__)

PAGE_MARKER = re.compile(r"<!--\s*page:\s*(\d+)\s*-->", re.IGNORECASE)
HEADING = re.compile(r"^(#{1,6}\s+.+|\d+(\.\d+)*\s+[A-Z][^.!?]{2,80})$")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
SUPPORTED_SUFFIXES = {".md", ".txt", ".pdf"}


# --------------------------------------------------------------------------- data types


@dataclass
class ManualPage:
    source: str  # file name, e.g. "centrifugal_pump_om_manual.md"
    page: int
    text: str
    title: str = ""
    meta: dict[str, str] = field(default_factory=dict)  # e.g. {"equipment": "pump"}


@dataclass
class Chunk:
    id: str
    text: str
    source: str
    title: str
    page: int
    section: str
    doc_sha: str
    meta: dict[str, str] = field(default_factory=dict)

    def metadata(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "title": self.title,
            "page": self.page,
            "section": self.section,
            "doc_sha": self.doc_sha,
            **self.meta,
        }


class Citation(BaseModel):
    """One retrieved manual passage. `ref` is what the LLM and the UI cite, e.g. [S1]."""

    ref: str = ""
    chunk_id: str
    source: str
    title: str = ""
    page: int
    section: str = ""
    score: float  # cosine similarity, higher is better
    text: str

    def label(self) -> str:
        sec = f", {self.section}" if self.section else ""
        return f"{self.title or self.source}, p. {self.page}{sec}"


class IngestReport(BaseModel):
    source: str
    status: str  # "added" | "skipped" | "replaced" | "empty"
    chunks: int


class Embedder(Protocol):
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


class NomicPrefixEmbedder:
    """nomic-embed-text is trained with task prefixes; using them noticeably helps retrieval."""

    def __init__(self, inner: Embedder) -> None:
        self.inner = inner

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.inner.embed_documents([f"search_document: {t}" for t in texts])

    def embed_query(self, text: str) -> list[float]:
        return self.inner.embed_query(f"search_query: {text}")


# --------------------------------------------------------------------------- cleaning / chunking


def clean_text(text: str) -> str:
    """Normalise OCR/PDF text while keeping paragraph breaks."""
    text = unicodedata.normalize("NFKC", text).replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[^\S\n\t]+", " ", text)  # odd spaces -> single space
    text = "".join(ch for ch in text if ch in "\n\t" or unicodedata.category(ch)[0] != "C")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)  # de-hyphenate words split across lines
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def _pack(parts: list[str], limit: int, sep: str) -> list[str]:
    out, cur = [], ""
    for part in parts:
        if cur and len(cur) + len(part) + len(sep) > limit:
            out.append(cur)
            cur = part
        else:
            cur = f"{cur}{sep}{part}" if cur else part
    return [*out, cur] if cur else out


def _split_long(par: str, limit: int) -> list[str]:
    """Split an oversized paragraph on line breaks (list items), then sentences, then hard."""
    if len(par) <= limit:
        return [par]
    lines: list[str] = []
    for line in par.splitlines():
        lines.extend(_pack(SENTENCE_END.split(line), limit, " ") if len(line) > limit else [line])
    return [p[i : i + limit] for p in _pack(lines, limit, "\n") for i in range(0, len(p), limit)]


def _tail(text: str, overlap: int) -> str:
    """Last ~overlap chars, starting at a sentence boundary where possible."""
    if overlap <= 0 or len(text) <= overlap:
        return text if overlap > 0 else ""
    tail = text[-overlap:]
    m = SENTENCE_END.search(tail)
    return tail[m.end() :] if m and m.end() < len(tail) else tail


def chunk_pages(
    pages: Sequence[ManualPage], chunk_chars: int | None = None, overlap: int | None = None
) -> list[Chunk]:
    """Heading-aware chunking. Chunks never cross pages, so every chunk has one page number."""
    s = get_settings()
    size = chunk_chars or s.rag_chunk_chars
    ovl = s.rag_chunk_overlap if overlap is None else overlap
    if not pages:
        return []
    doc_sha = hashlib.sha256(
        "\n\f".join(clean_text(p.text) for p in sorted(pages, key=lambda p: p.page)).encode()
    ).hexdigest()
    chunks: list[Chunk] = []
    section = ""
    for page in sorted(pages, key=lambda p: p.page):
        pieces: list[tuple[str, str]] = []  # (text, section)
        cur, cur_section = "", section
        for par in _paragraphs(clean_text(page.text)):
            first_line = par.splitlines()[0].strip()
            if HEADING.match(first_line) and len(first_line) < 100:
                pieces.append((cur, cur_section))
                section = first_line.lstrip("#").strip()
                cur, cur_section = par, section
                continue
            for piece in _split_long(par, size):
                # a chunk no longer than the overlap would just be duplicated: merge instead
                if len(cur) > ovl and len(cur) + len(piece) + 2 > size:
                    pieces.append((cur, cur_section))
                    cur = f"{_tail(cur, ovl)}\n\n{piece}".strip() if ovl else piece
                    cur_section = section
                else:
                    cur = f"{cur}\n\n{piece}".strip()
        pieces.append((cur, cur_section))
        for text, sec in pieces:
            if text.strip().lstrip("#").strip() not in ("", sec):  # skip empty/heading-only
                chunks.append(_make_chunk(page, len(chunks), text.strip(), sec, doc_sha))
    return chunks


def _make_chunk(page: ManualPage, idx: int, text: str, section: str, doc_sha: str) -> Chunk:
    digest = hashlib.sha1(f"{page.source}|{page.page}|{idx}|{text}".encode()).hexdigest()
    return Chunk(
        id=f"{_slug(page.source)}-p{page.page}-{digest[:12]}",
        text=text,
        source=page.source,
        title=page.title,
        page=page.page,
        section=section,
        doc_sha=doc_sha,
        meta=dict(page.meta),
    )


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40]


# --------------------------------------------------------------------------- loading


def _front_matter(text: str) -> tuple[dict[str, str], str]:
    m = FRONT_MATTER.match(text)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip().lower()] = v.strip()
    return meta, text[m.end() :]


def load_document(path: Path) -> list[ManualPage]:
    """Read a .md/.txt manual (pages marked with `<!-- page: N -->`) or a digital PDF."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        import pymupdf  # local import: only needed for PDFs

        with pymupdf.open(path) as doc:
            title = (doc.metadata or {}).get("title") or path.stem
            return [
                ManualPage(path.name, i + 1, page.get_text(), title)
                for i, page in enumerate(doc)
                if page.get_text().strip()
            ]
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError(f"Unsupported manual format: {path.name}")
    meta, text = _front_matter(path.read_text(encoding="utf-8"))
    title = meta.pop("title", "") or next(
        (ln.lstrip("#").strip() for ln in text.splitlines() if ln.startswith("# ")), path.stem
    )
    parts = PAGE_MARKER.split(text)
    if len(parts) == 1:
        pages = text.split("\f") if "\f" in text else [text]
        numbered = list(enumerate(pages, start=1))
    else:  # ["before", "1", "page1 text", "2", "page2 text", ...]
        numbered = [(int(parts[i]), parts[i + 1]) for i in range(1, len(parts) - 1, 2)]
    return [ManualPage(path.name, n, t, title, meta) for n, t in numbered if t.strip()]


def pages_from_records(records: Iterable[dict[str, Any]]) -> list[ManualPage]:
    """Adapter for extracted text from the ingestion/OCR pipeline.

    Each record needs `source`, `page` and `text`; `title` and other string fields are kept
    as metadata.
    """
    pages = []
    for r in records:
        missing = {"source", "page", "text"} - r.keys()
        if missing:
            raise ValueError(f"OCR record missing fields {sorted(missing)}: {r!r:.120}")
        extra = {
            k: str(v)
            for k, v in r.items()
            if k not in {"source", "page", "text", "title"} and v is not None
        }
        pages.append(
            ManualPage(str(r["source"]), int(r["page"]), str(r["text"]), r.get("title", ""), extra)
        )
    return pages


# --------------------------------------------------------------------------- store


class ManualStore:
    """ChromaDB collection of manual chunks with explicit (local) embeddings."""

    def __init__(self, collection: Any, embedder: Embedder) -> None:
        self.collection = collection
        self.embedder = embedder

    @classmethod
    def from_settings(
        cls,
        embedder: Embedder | None = None,
        collection_name: str | None = None,
        ephemeral: bool = False,
    ) -> ManualStore:
        """Store backed by the Chroma server (CHROMA_HOST), the embedded store (CHROMA_DIR),
        or, with `ephemeral=True`, an in-memory collection that is never persisted."""
        s = get_settings()
        os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")  # no telemetry egress
        import chromadb
        from chromadb.config import Settings as ChromaSettings

        chroma_settings = ChromaSettings(anonymized_telemetry=False)
        if ephemeral:
            client = chromadb.EphemeralClient(settings=chroma_settings)
        elif s.chroma_host:
            client = chromadb.HttpClient(
                host=s.chroma_host, port=s.chroma_port, settings=chroma_settings
            )
        else:
            client = chromadb.PersistentClient(path=str(s.chroma_dir), settings=chroma_settings)
        collection = client.get_or_create_collection(
            collection_name or s.chroma_collection, metadata={"hnsw:space": "cosine"}
        )
        if embedder is None:
            from app.agent.llm import get_embeddings

            embedder = get_embeddings()
            if "nomic" in s.embed_model:
                embedder = NomicPrefixEmbedder(embedder)
        return cls(collection, embedder)

    def count(self) -> int:
        return int(self.collection.count())

    def _existing_sha(self, source: str) -> str | None:
        got = self.collection.get(where={"source": source}, limit=1, include=["metadatas"])
        metas = got.get("metadatas") or []
        return metas[0].get("doc_sha") if metas else None

    def ingest(self, pages: Sequence[ManualPage], batch: int = 32) -> list[IngestReport]:
        """Index pages grouped by source. Unchanged sources are skipped, changed ones replaced."""
        by_source: dict[str, list[ManualPage]] = {}
        for p in pages:
            by_source.setdefault(p.source, []).append(p)
        reports = []
        for source, src_pages in by_source.items():
            chunks = chunk_pages(src_pages)
            if not chunks:
                reports.append(IngestReport(source=source, status="empty", chunks=0))
                continue
            old = self._existing_sha(source)
            if old == chunks[0].doc_sha:
                log.info("manual unchanged, skipping: %s", source)
                reports.append(IngestReport(source=source, status="skipped", chunks=0))
                continue
            if old is not None:
                self.collection.delete(where={"source": source})
            for i in range(0, len(chunks), batch):
                part = chunks[i : i + batch]
                self.collection.add(
                    ids=[c.id for c in part],
                    documents=[c.text for c in part],
                    metadatas=[c.metadata() for c in part],
                    embeddings=self.embedder.embed_documents([_embed_text(c) for c in part]),
                )
            status = "replaced" if old else "added"
            log.info("manual %s: %s (%d chunks)", status, source, len(chunks))
            reports.append(IngestReport(source=source, status=status, chunks=len(chunks)))
        return reports

    def search(
        self,
        query: str,
        k: int | None = None,
        equipment: str | None = None,
        max_distance: float | None = None,
    ) -> list[Citation]:
        """Semantic search. Passages weaker than `max_distance` are dropped, not padded."""
        s = get_settings()
        k = k or s.rag_top_k
        limit = s.rag_max_distance if max_distance is None else max_distance
        if not query.strip() or self.count() == 0:
            return []
        where = {"equipment": equipment} if equipment else None
        res = self.collection.query(
            query_embeddings=[self.embedder.embed_query(query)],
            n_results=k,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        ids, docs = res["ids"][0], res["documents"][0]
        metas, dists = res["metadatas"][0], res["distances"][0]
        if not ids and equipment:  # metadata filter too strict -> retry unfiltered
            return self.search(query, k, None, max_distance)
        out = []
        for cid, doc, meta, dist in zip(ids, docs, metas, dists, strict=True):
            if dist > limit:
                continue
            out.append(
                Citation(
                    chunk_id=cid,
                    source=meta.get("source", ""),
                    title=meta.get("title", ""),
                    page=int(meta.get("page", 0)),
                    section=meta.get("section", ""),
                    score=round(1.0 - float(dist), 4),
                    text=doc,
                )
            )
        return out


def _embed_text(c: Chunk) -> str:
    """Prefix the heading so short chunks keep their context in embedding space."""
    head = " / ".join(x for x in (c.title, c.section) if x)
    return f"{head}\n{c.text}" if head else c.text


def ingest_directory(store: ManualStore, directory: Path) -> list[IngestReport]:
    files = sorted(p for p in directory.rglob("*") if p.suffix.lower() in SUPPORTED_SUFFIXES)
    pages: list[ManualPage] = []
    for f in files:
        try:
            pages.extend(load_document(f))
        except Exception:
            log.exception("could not read manual %s", f)
    return store.ingest(pages)
