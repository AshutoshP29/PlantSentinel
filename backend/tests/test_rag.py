import pytest

from app.agent.rag import (
    ManualPage,
    ManualStore,
    NomicPrefixEmbedder,
    chunk_pages,
    clean_text,
    ingest_directory,
    load_document,
    pages_from_records,
)
from tests.agent_helpers import MANUALS, HashEmbedder, MemoryCollection, memory_store

PUMP_MANUAL = MANUALS / "centrifugal_pump_om_manual.md"


def test_clean_text_normalises_ocr_noise() -> None:
    raw = "Mech" + chr(0xA0) + "seal  faces were re-\nplaced.\r\n\r\n\r\n\r\nNext\x07 para"
    assert clean_text(raw) == "Mech seal faces were replaced.\n\nNext para"


def test_load_document_reads_pages_title_and_front_matter() -> None:
    pages = load_document(PUMP_MANUAL)
    assert [p.page for p in pages] == list(range(1, 9))
    assert pages[0].title.startswith("CP-200 Series")
    assert pages[0].meta == {"equipment": "pump", "doc_type": "oem_manual"}


def test_chunks_keep_page_section_and_size() -> None:
    chunks = chunk_pages(load_document(PUMP_MANUAL), chunk_chars=900, overlap=150)
    assert all(len(c.text) <= 900 + 150 for c in chunks)
    seal = [c for c in chunks if c.section == "5.1 Mechanical seal leakage"]
    assert seal and seal[0].page == 5 and "heat checking" in seal[0].text
    assert len({c.id for c in chunks}) == len(chunks)
    assert len({c.doc_sha for c in chunks}) == 1


def test_long_procedure_split_without_duplicate_fragments() -> None:
    chunks = [c for c in chunk_pages(load_document(PUMP_MANUAL)) if c.page == 6]
    assert len(chunks) == 2
    assert all(len(c.text) > 300 for c in chunks)


def test_pages_from_records_validates() -> None:
    pages = pages_from_records(
        [{"source": "scan_01.pdf", "page": 2, "text": "Seal leaking", "tag": "P-101"}]
    )
    assert pages[0].meta == {"tag": "P-101"} and pages[0].page == 2
    with pytest.raises(ValueError, match="missing fields"):
        pages_from_records([{"source": "x", "text": "y"}])


def test_ingest_is_idempotent_and_replaces_changed_documents() -> None:
    store = memory_store()
    first = ingest_directory(store, MANUALS)
    assert {r.status for r in first} == {"added"}
    n = store.count()
    assert {r.status for r in ingest_directory(store, MANUALS)} == {"skipped"}
    assert store.count() == n

    changed = [ManualPage("centrifugal_pump_om_manual.md", 1, "Completely new text.", "CP-200")]
    assert store.ingest(changed)[0].status == "replaced"
    assert store.count() < n


def test_search_returns_cited_passages() -> None:
    store = memory_store()
    ingest_directory(store, MANUALS)
    hits = store.search("mechanical seal face overheating loss of flush heat checking", k=3)
    assert hits
    top = hits[0]
    assert top.source.endswith(".md") and top.page >= 1 and top.title
    assert 0 < top.score <= 1
    assert "flush" in top.text.lower()
    assert "p." in top.label()


def test_search_drops_irrelevant_matches() -> None:
    store = memory_store()
    ingest_directory(store, MANUALS)
    assert store.search("quarterly marketing budget spreadsheet", max_distance=0.6) == []


def test_search_on_empty_store() -> None:
    assert memory_store().search("seal") == []


def test_equipment_filter_falls_back_when_nothing_matches() -> None:
    store = memory_store()
    ingest_directory(store, MANUALS)
    assert store.search("mechanical seal leakage", equipment="compressor", max_distance=1.0)


def test_nomic_prefixes() -> None:
    class Spy(HashEmbedder):
        def __init__(self) -> None:
            self.seen: list[str] = []

        def embed_documents(self, texts):
            self.seen.extend(texts)
            return super().embed_documents(texts)

        def embed_query(self, text):
            self.seen.append(text)
            return super().embed_query(text)

    spy = Spy()
    emb = NomicPrefixEmbedder(spy)
    emb.embed_documents(["a"])
    emb.embed_query("b")
    assert spy.seen == ["search_document: a", "search_query: b"]


def test_real_chromadb_roundtrip(tmp_path) -> None:
    """Same flow against a real (ephemeral) ChromaDB, skipped where chromadb can't load."""
    try:
        import chromadb
        from chromadb.config import Settings
    except Exception as exc:  # e.g. native module blocked by OS application control
        pytest.skip(f"chromadb not importable here: {exc}")
    client = chromadb.PersistentClient(
        path=str(tmp_path / "chroma"), settings=Settings(anonymized_telemetry=False)
    )
    col = client.get_or_create_collection("test_manuals", metadata={"hnsw:space": "cosine"})
    store = ManualStore(col, HashEmbedder())
    assert {r.status for r in ingest_directory(store, MANUALS)} == {"added"}
    assert {r.status for r in ingest_directory(store, MANUALS)} == {"skipped"}
    hits = store.search("shaft alignment tolerance parallel offset", k=2)
    assert hits and hits[0].section == "7 Shaft alignment"
    assert isinstance(MemoryCollection().count(), int)


def test_from_settings_picks_chroma_server_when_host_is_set(monkeypatch) -> None:
    """CHROMA_HOST set (Docker) -> HttpClient; unset (local) -> embedded PersistentClient."""
    try:
        import chromadb
    except Exception as exc:
        pytest.skip(f"chromadb not importable here: {exc}")
    from app import config

    calls: list[tuple[str, dict]] = []

    class FakeClient:
        def get_or_create_collection(self, *_args, **_kwargs) -> MemoryCollection:
            return MemoryCollection()

    def fake(kind: str):
        def make(**kwargs) -> FakeClient:
            calls.append((kind, kwargs))
            return FakeClient()

        return make

    monkeypatch.setattr(chromadb, "HttpClient", fake("http"))
    monkeypatch.setattr(chromadb, "PersistentClient", fake("embedded"))

    ManualStore.from_settings(HashEmbedder())
    monkeypatch.setenv("CHROMA_HOST", "chroma")
    monkeypatch.setenv("CHROMA_PORT", "8000")
    config.get_settings.cache_clear()
    ManualStore.from_settings(HashEmbedder())

    assert [kind for kind, _ in calls] == ["embedded", "http"]
    assert calls[1][1]["host"] == "chroma" and calls[1][1]["port"] == 8000
